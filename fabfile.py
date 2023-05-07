import logging
import os
import sys

# AWS api
import boto3
import botocore
from botocore.exceptions import ClientError
from dotenv import dotenv_values

# The most basic use of Fabric is to execute a shell command on a remote system via SSH,
# then (optionally) interrogate the result. Teh
from fabric import task

# use loggers right from the start, rather than "print"
logger = logging.getLogger(__name__)
# this will log boto output to std out
logging.basicConfig(stream=sys.stdout, level=logging.INFO)

kn = "cloud"
# Availability Zone / Region Name
rn = "us-east-1"
# (Cloud9 Ubuntu - 2021-10-28T1333)
ami = "ami-05e4673d4a28889fe"

ssh_key_path = "~/.ssh/cloud.pem"

key_name = "cloud"

init_script = """#!/bin/bash
    docker pull pc2558544545/dist-cnn:0.20
    """


def makesecgroup():
    ec2_client = boto3.client("ec2", region_name=rn)

    # my_public_ip = os.popen(
    #     'dig +short myip.opendns.com @resolver1.opendns.com').read().strip()
    # my_public_ip += "/32"

    try:
        response = ec2_client.create_security_group(
            GroupName="dist-cnn-sec-group",
            Description="Ports configurations of inter-swarm communication",
        )
        security_group_id = response["GroupId"]

        data = ec2_client.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    "IpProtocol": "tcp",
                    "FromPort": 2377,
                    "ToPort": 2377,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 0,
                    "ToPort": 65535,
                    "IpRanges": [{"CidrIp": "172.31.0.0/16"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 22,
                    "ToPort": 22,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "udp",
                    "FromPort": 7946,
                    "ToPort": 7946,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 7946,
                    "ToPort": 7946,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "tcp",
                    "FromPort": 2181,
                    "ToPort": 2181,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
                {
                    "IpProtocol": "udp",
                    "FromPort": 4789,
                    "ToPort": 4789,
                    "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                },
            ],
        )
        print("Ingress Successfully Set %s" % data)
        return security_group_id

    except ClientError as e:
        print(e)
        print("Returning the id of the exisiting sec-group")
        response = ec2_client.describe_security_groups(
            GroupNames=["dist-cnn-sec-group"]
        )
        return response["SecurityGroups"][0]["GroupId"]


# ===========================================================================
#                                EC2
# ===========================================================================

# ---------------------------------------------------------------------------
#                            c == context
# ---------------------------------------------------------------------------


@task
def ec2make(c, name, amount, securitygroup):
    ec2_resource = boto3.resource("ec2", region_name=rn)

    instances = ec2_resource.create_instances(
        ImageId=ami,
        MinCount=1,
        MaxCount=int(amount),
        InstanceType="c5d.large",
        # InstanceType="m5.large",
        Placement={
            "AvailabilityZone": "us-east-1a",
        },
        SecurityGroupIds=[securitygroup] if securitygroup else [],
        KeyName=key_name,
        UserData=init_script,
        BlockDeviceMappings=[
            {
                "DeviceName": "/dev/sda1",
                "Ebs": {
                    "VolumeSize": 50,
                },
            }
        ],
    )
    device_index = 0

    for index, instance in enumerate(instances):
        instance.wait_until_running()
        iid = instance.id
        logger.info(instance)
        # give the instance a tag name
        ec2_resource.create_tags(
            Resources=[iid], Tags=[{"Key": "Name", "Value": name + str(device_index)}]
        )
        device_index += 1


@task
def ec2ssh(c, name):
    """
    SSH in to a remote terminal
    name: remote host name
    """
    ec2_resource = boto3.resource("ec2", region_name=rn)
    instances = ec2_resource.instances.filter(
        Filters=[
            {"Name": "tag:Name", "Values": [name]},
        ]
    )
    for instance in instances:
        if instance.state["Name"] == "running":
            os.system(
                f"ssh -oStrictHostKeyChecking=no -i {ssh_key_path} ubuntu@{instance.public_ip_address}"
            )
    else:
        logging.info("No running instance of that name to ssh into")


@task
def ec2sshsh(c, name, sh, output=0):
    """
    SSH a bash script to a remote terminal and has the fetch any output spawned
    name: remote host name
    sh: bash script name
    """
    world_size = os.environ.get("WORLD_SIZE")
    ec2_resource = boto3.resource("ec2", region_name=rn)
    instances = ec2_resource.instances.filter(
        Filters=[
            {"Name": "tag:Name", "Values": [name]},
        ]
    )
    for instance in list(instances):
        if instance.state["Name"] == "running":
            # start the swarm manager on
            if output:
                os.system(
                    f"ssh -oStrictHostKeyChecking=no -i {ssh_key_path} ubuntu@{instance.public_ip_address} 'WORLD_SIZE={world_size} bash -s' < {sh} > tmp/output.txt"
                )
            else:
                os.system(
                    f"ssh -oStrictHostKeyChecking=no -i {ssh_key_path} ubuntu@{instance.public_ip_address} 'WORLD_SIZE={world_size} bash -s' < {sh}"
                )


@task
def setupmaster(c):
    ec2sshsh(c, "rank0", "./scripts/swarm_manager_setup.sh", 0)
    ec2sshsh(c, "rank0", "./scripts/fetch_swarm_token.sh", 1)
    os.system("sed '1d' tmp/output.txt > ./scripts/join_swarm.sh")


@task
def setupworkers(c):
    world_size = os.environ.get("WORLD_SIZE")

    for i in range(1, int(world_size) + 1):
        ec2sshsh(c, f"rank{i}", "./scripts/join_swarm.sh", 0)


@task
def distributejobs(c):
    ec2sshsh(c, "rank0", "./scripts/distribute_jobs.sh", 0)


@task
def start(c):
    world_size = os.environ.get("WORLD_SIZE")
    security_group_id = makesecgroup()
    ec2make(c, "rank", world_size, security_group_id)


@task
def ec2stop(c, name=None):
    ec2_resource = boto3.resource("ec2", region_name=rn)
    if name == None:
        # instances is an iterator
        instances = ec2_resource.instances.all()

    else:
        instances = ec2_resource.instances.filter(
            Filters=[
                {"Name": "tag:Name", "Values": [name]},
            ]
        )
    for instance in instances:
        if instance.state["Name"] == "running":
            instance.stop()


@task
def ec2kill(c, name=None):
    ec2_resource = boto3.resource("ec2", region_name=rn)
    if name == None:
        # instances is an iterator
        instances = ec2_resource.instances.all()

    else:
        instances = ec2_resource.instances.filter(
            Filters=[
                {"Name": "tag:Name", "Values": [name]},
            ]
        )
    for instance in instances:
        if instance.state["Name"] == "running":
            instance.terminate()


@task
def ec2info(c, name=None):
    """
    Return an EC2 Instance
    :return:
    """
    ec2_resource = boto3.resource("ec2", region_name=rn)
    # instances is an iterator
    instances = ec2_resource.instances.all()
    # ---------------------------------------------------------------------------
    #            Provide all EC2 instance details by default
    # ---------------------------------------------------------------------------
    if name == None:
        # instance_information = client.describe_instances()
        # for reservation in instance_information["Reservations"]:
        #     for instance in reservation["Instances"]:
        #         resource.Instance(instance["InstanceId"]).terminate()
        log_run_instances(instances)
        # ---------------------------------------------------------------------------
        #                          If name is provided
        # ---------------------------------------------------------------------------
    else:
        instances = ec2_resource.instances.filter(
            Filters=[
                {"Name": "tag:Name", "Values": [name]},
                # {"Name": "instance-state-name", "Values": ["running"]}
            ]
        )
        instances = list(instances)

        if len(instances) == 0:
            print("The instance does not exist")
            # return create(c, name=name)
        else:
            log_run_instances(instances)


def log_run_instances(instances):
    for instance in instances:
        if instance.state["Name"] == "running":
            dns = instance.public_dns_name
            internal_ip = instance.private_ip_address
            public_ip = instance.public_ip_address
            logger.info(
                f"Instance up and running at {dns} with internal ip {internal_ip}: {public_ip}: {internal_ip}"
            )
        else:
            logger.warning(f"instance {instance.id} not running")


# ===========================================================================
#                                S3
# ===========================================================================


@task
def s3make(c, name):
    """Create an S3 bucket
    :param bucket_name: Bucket to create
    :return: True if bucket created, else False
    """
    # Create bucket
    try:
        s3_client = boto3.client("s3", region_name=rn)
        # location = {"LocationConstraint": "us-east-1"}
        s3_client.create_bucket(Bucket=name)
    except ClientError as e:
        logging.error(e)
        return False
    return True


@task
def s3info(c):
    # Create an S3 client
    s3 = boto3.client(
        "s3",
        region_name=rn,
    )
    # Call S3 to list current buckets
    response = s3.list_buckets()
    # Get a list of all bucket names from the response
    buckets = [bucket["Name"] for bucket in response["Buckets"]]
    # Print out the bucket list
    print("Bucket List: %s" % buckets)


@task
def s3upload(
    c, filename="data/train.pkl", bucket="ge19260-dist-cnn-s3", object_name=None
):
    """Upload a file to an S3 bucket

    :param file_name: File to upload
    :param bucket: Bucket to upload to
    :param object_name: S3 object name. If not specified then file_name is used
    :return: True if file was uploaded, else False
    """
    # If S3 object_name was not specified, use file_name
    if object_name is None:
        object_name = os.path.basename(filename)

    # Upload the file
    s3_client = boto3.client(
        "s3",
        region_name=rn,
    )
    try:
        response = s3_client.upload_file(filename, bucket, object_name)
    except ClientError as e:
        logging.error(e)
        return False
    return True


@task
def s3kill(c, name=None):
    s3_resource = boto3.resource("s3", region_name=rn)
    s3_client = boto3.client("s3", region_name=rn)

    if name == None:
        response = s3_client.list_buckets()
        # Get a list of all bucket names from the response
        for bucket_info in response["Buckets"]:
            bucket = s3_resource.Bucket(bucket_info["Name"])
            bucket.objects.all().delete()
            s3_client.delete_bucket(Bucket=bucket_info["Name"])

    else:
        bucket = s3_resource.Bucket(bucket_info[name])
        bucket.objects.all().delete()
        s3_client.delete_bucket(Bucket=bucket_info[name])
