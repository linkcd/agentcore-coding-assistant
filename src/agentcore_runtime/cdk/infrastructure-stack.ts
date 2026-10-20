/**
 * Storage-only adaptation of awslabs/agentcore-samples coding_agents/infra/cfn-vpc.yaml.
 * The bucket and network are external. Runtime stacks own their profile access points.
 * See the repository NOTICE and runtime README for attribution and setup instructions.
 */
import { ArnFormat, CfnOutput, Fn, Stack, aws_iam as iam, aws_s3files as s3files } from "aws-cdk-lib";
import { Construct } from "constructs";
import { InfrastructureConfig } from "./infrastructure-config";

export interface RuntimeInfrastructure {
  account: string;
  region: string;
  subnetIds: string[];
  securityGroupIds: string[];
  fileSystemId: string;
  fileSystemArn: string;
}

export class InfrastructureStack extends Stack {
  readonly runtimeInfrastructure: RuntimeInfrastructure;

  constructor(scope: Construct, id: string, props: {
    account: string; region: string; stackName: string; config: InfrastructureConfig;
  }) {
    const { config } = props;
    super(scope, id, { stackName: props.stackName, env: { account: props.account, region: props.region },
      description: "S3 Files storage for AgentCore coding agents using an external network" });
    // The sample's service permissions belong to this filesystem role, never to worker roles.
    const bucketArn = this.formatArn({ service: "s3", region: "", account: "", resource: config.bucketName });
    const objectsArn = `${bucketArn}/*`;
    const filesRole = new iam.CfnRole(this, "S3FilesRole", {
      assumeRolePolicyDocument: { Version: "2012-10-17", Statement: [{ Effect: "Allow",
        Principal: { Service: "elasticfilesystem.amazonaws.com" }, Action: "sts:AssumeRole" }] },
      policies: [{ policyName: "s3files-bucket-access", policyDocument: {
        Version: "2012-10-17", Statement: [
          { Effect: "Allow", Action: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket",
            "s3:GetBucketLocation", "s3:AbortMultipartUpload", "s3:DeleteObject*", "s3:GetObject*",
            "s3:List*", "s3:PutObject*", "s3:ListBucketVersions"], Resource: [bucketArn, objectsArn] },
          { Sid: "UseKmsKeyWithS3Files", Effect: "Allow", Action: ["kms:GenerateDataKey", "kms:Encrypt",
            "kms:Decrypt", "kms:ReEncryptFrom", "kms:ReEncryptTo"], Condition: { StringLike: {
              "kms:ViaService": Fn.sub("s3.${AWS::Region}.amazonaws.com"),
              "kms:EncryptionContext:aws:s3:arn": [bucketArn, objectsArn],
            } }, Resource: this.formatArn({ service: "kms", resource: "*" }) },
          { Sid: "EventBridgeManage", Effect: "Allow", Action: ["events:DeleteRule", "events:DisableRule",
            "events:EnableRule", "events:PutRule", "events:PutTargets", "events:RemoveTargets"],
            Condition: { StringEquals: { "events:ManagedBy": "elasticfilesystem.amazonaws.com" } },
            Resource: [this.formatArn({ service: "events", region: "*", account: "*", resource: "rule",
              resourceName: "DO-NOT-DELETE-S3-Files*", arnFormat: ArnFormat.SLASH_RESOURCE_NAME })] },
          { Sid: "EventBridgeRead", Effect: "Allow", Action: ["events:DescribeRule", "events:ListRuleNamesByTarget",
            "events:ListRules", "events:ListTargetsByRule"], Resource: [this.formatArn({ service: "events",
              region: "*", account: "*", resource: "rule", resourceName: "*", arnFormat: ArnFormat.SLASH_RESOURCE_NAME })] },
        ],
      } }],
    });
    const files = new s3files.CfnFileSystem(this, "S3FilesFileSystem", {
      bucket: bucketArn, roleArn: filesRole.attrArn,
    });
    files.addResourceDependency(filesRole);
    config.subnetIds.forEach((subnetId, index) => {
      new s3files.CfnMountTarget(this, `S3FilesMountTarget${index + 1}`, {
        fileSystemId: files.attrFileSystemId, subnetId, securityGroups: config.securityGroupIds,
      });
    });
    for (const [key, value] of Object.entries({
      S3FilesFileSystemId: files.attrFileSystemId, S3FilesFileSystemArn: files.attrFileSystemArn,
      S3FilesRoleArn: filesRole.attrArn,
    })) new CfnOutput(this, key, { value });
    this.runtimeInfrastructure = {
      account: props.account, region: props.region, subnetIds: config.subnetIds,
      securityGroupIds: config.securityGroupIds, fileSystemId: files.attrFileSystemId, fileSystemArn: files.attrFileSystemArn,
    };
  }
}
