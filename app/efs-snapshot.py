#!/usr/bin/env python

import boto3
import paramiko
import math
from time import sleep
from subprocess import call

AMI_ID = 'ami-ebd02392'
INSTANCE_TYPE = 't2.micro'
INSTANCE_COUNTER = 0


def main():

    efs_volumes = get_efs_volumes()
    for volume in efs_volumes:
        trigger_snapshot(volume)


# Query all EFS volumes, and add to a list
def get_efs_volumes():
    efs_volumes = list()
    efs = boto3.client('efs')
    paginator = efs.get_paginator('describe_file_systems')
    response_iterator = paginator.paginate(
        PaginationConfig={
             'MaxItems': 1000,
             'PageSize': 123})
    for page in response_iterator:
        for fs in page['FileSystems']:
            efs_volumes.append(fs)

    return efs_volumes


def trigger_snapshot(volume):
    global INSTANCE_COUNTER

    # Gather file size of EFS volume, round up to nearest GB.  This will be used to determine the EBS volume size.
    file_system_id = volume['FileSystemId']
    file_size = str(bytesto(volume['SizeInBytes']['Value'], 'g'))
    ebs_size = int(math.ceil(float(file_size)))

    # Generate a new keypair
    key_pair = generate_keypair()

    # AWS Boto3 resources
    ec2_resource = boto3.resource('ec2')
    ec2_client = boto3.client('ec2')

    # Create temporary security group with SSH port open
    security_group_name = 'ephemeral_efs_snapshot-' + str(INSTANCE_COUNTER)
    security_group = ec2_client.create_security_group(
        Description='Temporary security group for making EFS snapshots',
        GroupName=security_group_name,
    )
    security_group = ec2_resource.SecurityGroup(security_group['GroupId'])
    security_group.authorize_ingress(
        IpProtocol="tcp",
        CidrIp="0.0.0.0/0",
        FromPort=22,
        ToPort=22)

    # Create the EC2 Instance
    instance = ec2_resource.create_instances(
        BlockDeviceMappings=[
            {
                'DeviceName': '/dev/sdh',
                'VirtualName': 'ephemeral0',
                'Ebs': {
                    'Encrypted': False,
                    'DeleteOnTermination': True,
                    'VolumeSize': ebs_size,
                    'VolumeType': 'standard'
                },
            },
        ],
        KeyName=key_pair['KeyName'],
        ImageId=AMI_ID,
        MinCount=1,
        MaxCount=1,
        InstanceType='t2.micro',
        SecurityGroupIds=[security_group.id])

    ec2_instance = ec2_resource.Instance(instance[0].id)
    print 'Waiting for ' + instance[0].id + ' to become ready...'
    ec2_instance.wait_until_running()
    print('OK, running now!')

    # Provision the EC2 instance via SSH
    provision_instance(ec2_instance, volume)

    # Snapshot the EBS volume which now has the copied files
    ec2_volume_id = ec2_instance.block_device_mappings[1]['Ebs']['VolumeId']
    print 'Sleeping for 60 seconds to ensure write cache is committed to disk'
    sleep(60)
    response = ec2_client.create_snapshot(
        Description='Snapshot of EFS Volume ' + file_system_id,
        VolumeId=ec2_volume_id
    )
    print 'Snapshot Created: ' + str(response)

    # Terminate the EC2 Instance
    response = ec2_client.terminate_instances(
        InstanceIds=[
            str(instance[0].id),
        ],
    )
    print 'Terminating instance ' + str(instance[0].id) + '...'
    ec2_instance.wait_until_terminated()
    print 'Instance ' + str(instance[0].id) + 'Terminated' + str(response)

    # Delete the temporary security group
    ec2_client.delete_security_group(
        GroupName=security_group_name
    )
    print 'Security group \'ephemeral_efs_snapshot\' deleted'

    # Delete local pem key as it will no longer be needed
    call(["rm", "ephemeral_key_for_efs_snapshot.pem"])

    INSTANCE_COUNTER += 1


# SSH onto new created EC2 instance, mount the EFS volume, and copy over its files to EBS.
def provision_instance(ec2_instance, volume):
    interval = 10
    k = paramiko.RSAKey.from_private_key_file("ephemeral_key_for_efs_snapshot.pem")
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    host = ec2_instance.public_dns_name
    try:
        print("Sleeping for 60 seconds to give time for the instance to come up")
        sleep(60)
        print "Attempting to connect to " + host + " (This may take some time)...."
        c.connect(hostname=host, username="ec2-user", pkey=k)
    except (paramiko.ssh_exception.BadHostKeyException,
            paramiko.ssh_exception.AuthenticationException,
            paramiko.ssh_exception.SSHException,
            paramiko.ssh_exception.socket.error) as e:
        print e
        sleep(interval)

    print "Connected to " + host
    # TODO - expand on this so 'eu-west-1' isn't hard coded.
    commands = [
        "sudo yum install -y nfs-utils",
        "sudo yum install",
        "sudo mkdir efs",
        "sudo mkdir snapshot",
        "sudo mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2 "
        + volume['FileSystemId'] + ".efs.eu-west-1.amazonaws.com:/ efs",
        "sudo mkfs -t ext4 /dev/xvdh",
        "sudo mount /dev/xvdh snapshot",
        "sudo cp -Rp efs/* snapshot/",
    ]

    for command in commands:
        print "Executing {}".format(command)
        stdin, stdout, stderr = c.exec_command(command)
        print stdout.read()
        print stderr.read()

    return {
        'message': "Script execution completed."
    }


# Generate a key pair that will be used for creating an EC2 instance (which can then be provisioned)
def generate_keypair():
    ec2 = boto3.client('ec2')
    print 'Deleting ephemeral key pair from AWS if it exists'
    ec2.delete_key_pair(KeyName='ephemeral_key_for_efs_snapshot')
    print 'Generating new key pair'
    key_pair = ec2.create_key_pair(KeyName='ephemeral_key_for_efs_snapshot')
    f = open("ephemeral_key_for_efs_snapshot.pem", "w+")
    f.write(key_pair['KeyMaterial'])
    f.close()
    call(["chmod", "400", "ephemeral_key_for_efs_snapshot.pem"])
    return key_pair


# Converts 'bytes' to other size (ie. GB)
def bytesto(bytes, to, bsize=1024):
    a = {'k': 1, 'm': 2, 'g': 3, 't': 4, 'p': 5, 'e': 6}
    r = float(bytes)
    for i in range(a[to]):
        r = r / bsize

    return r


if __name__ == '__main__':
    main()

