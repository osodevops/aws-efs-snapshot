# EFS Snapshot Tool
## Overview
Presently, there is no way to 'snapshot' an EFS backed volume on AWS.  To overcome this, we have created a script which will effectively:

* Pull a list of all EFS volumes on the account, and then for each volume, it will:
  * Create an ephemeral 'Key Pair', 'Security Group', EC2 Instance', and EBS volume (calculated to be slightly larger than the EFS volume it will be backing up).
  * Copy the EFS data to the newly created EBS Volume
  * Snapshot the EBS Volume
  * Destroy the Key Pair, Security Group, EC2 Instance, and EBS volume
  
### Before Running...
Before running, AWS credentials/config, need to be provided.

#### AWS Credentials
* Copy the 'credentials' and 'config' AWS files that are typically found in $HOME/.aws into the folder /aws-credentials.  If you do not havev these files, please see [here](https://docs.aws.amazon.com/cli/latest/userguide/cli-config-files.html)

#### How to run

##### Docker Build
```docker build . -t <<BUILD_NAME>>:latest```

##### Docker Run
```docker run -it -v $(pwd)/aws-credentials:/root/.aws <<BUILD_NAME>>:latest```

### Note
Presently this script is only built to work for eu-west-1