"""Guided setup for real AWS credentials and deployment prerequisites."""

from __future__ import annotations

import streamlit as st

from aidevops.ui.aws_dashboard import _aws_api


def render(api, session_cookie=None) -> None:
    st.title("Set up real AWS")
    st.caption(
        "Configure credentials on the computer running the FastAPI backend, then verify "
        "which AWS account Aidevops will use."
    )
    st.info(
        "Aidevops never asks for or stores AWS access keys in this page. Use an AWS CLI "
        "profile or an IAM role on the backend host. A LocalStack auth token is not an AWS credential."
    )

    st.subheader("1. Create a backend credential profile")
    st.write(
        "For a local Windows setup, AWS IAM Identity Center (SSO) is recommended. "
        "Install AWS CLI v2, then run these commands in a terminal on the backend computer:"
    )
    st.code(
        "aws configure sso --profile aidevops\n"
        "aws sso login --profile aidevops\n"
        "aws sts get-caller-identity --profile aidevops",
        language="powershell",
    )
    st.markdown(
        "[AWS CLI SSO setup](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-sso.html) · "
        "[Install AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)"
    )
    with st.expander("Using an existing IAM access-key profile"):
        st.write(
            "Run `aws configure --profile aidevops` in the backend host's terminal. "
            "The AWS CLI writes credentials to the user's AWS credentials folder, not to Aidevops. "
            "Prefer SSO or short-lived credentials; never paste keys into Streamlit, chat, source code, "
            "or the project `.env`."
        )

    st.subheader("2. Select real AWS in the backend configuration")
    st.write(
        "Edit the repository-root `.env` on the backend computer. These are configuration values, "
        "not access keys:"
    )
    st.code(
        "AIDEVOPS_AWS_MODE=aws\n"
        "AWS_PROFILE=aidevops\n"
        "AIDEVOPS_AWS_REGION=us-east-1\n"
        "AIDEVOPS_AWS_EC2_AMI_ID=ami-replace-with-an-available-regional-ami\n"
        "AIDEVOPS_AWS_EC2_INSTANCE_PROFILE_ARN="
        "arn:aws:iam::<account-id>:instance-profile/<profile-name>",
        language="dotenv",
    )
    st.warning(
        "Use an AMI and instance profile from the real AWS account and selected region. "
        "Do not reuse the LocalStack AMI or LocalStack instance-profile ARN. Restart the "
        "FastAPI backend after changing `.env`."
    )

    st.subheader("3. Ask your AWS administrator for scoped permissions")
    st.write(
        "The backend profile needs `sts:GetCallerIdentity`, `ec2:DescribeImages` and the EC2 "
        "launch/security-group actions; ECR repository creation, image push and image verification "
        "(`ecr:DescribeImages`); and "
        "`iam:PassRole` limited to the selected instance profile's role. To validate deployment "
        "before creating resources, it also needs `iam:GetInstanceProfile` and "
        "`iam:SimulatePrincipalPolicy`. AWS management additionally needs EC2 describe/start/stop/"
        "reboot/terminate/launch permissions, `ssm:DescribeInstanceInformation`, `ssm:SendCommand`, "
        "`ssm:GetCommandInvocation`, `cloudwatch:GetMetricStatistics`, and "
        "`ce:GetCostAndUsage`. Scope write permissions to the intended region and resources. "
        "S3 deployments additionally need bucket creation, object upload, website/policy "
        "configuration, and cleanup actions."
    )
    with st.expander("EC2 instance profile and deployment safety"):
        st.write(
            "The EC2 instance profile is separate from the backend credential profile. Its role must "
            "allow the instance to use Systems Manager and, when pulling an ECR image, read from "
            "ECR. Attach `AmazonSSMManagedInstanceCore` for SSM connectivity and "
            "`AmazonEC2ContainerRegistryReadOnly` for ECR image pulls to that instance role (not "
            "the backend profile). SSM actions require the agent to be online and outbound network "
            "access. S3 hosts static website files only; it does not run Docker containers. The "
            "AWS management page supports manual refresh and requests CloudWatch metrics only when "
            "you ask; remote Docker commands use an allowlist and never accept arbitrary shell text. "
            "Creating or terminating instances and deploying a container require explicit confirmation. "
            "These actions can incur AWS charges."
        )

    st.subheader("Test the backend connection")
    st.caption(
        "This checks AWS identity only (STS); it does not prove that the profile has all deployment permissions."
    )
    st.caption(
        "If an IAM Identity Center session expired, run `aws sso login --profile aidevops` "
        "on the backend computer, then check again. No backend restart is needed for an SSO refresh."
    )
    if st.button("Check AWS connection", key="aws_setup_check", type="primary"):
        result, error = _aws_api(api, session_cookie, "GET", "/api/aws/status")
        if error:
            st.error(error)
        elif not result.get("available"):
            st.error(result.get("message") or "AWS credentials could not be verified.")
        elif result.get("mode") != "aws":
            st.warning(
                "The backend is connected to LocalStack, not real AWS. Set "
                "`AIDEVOPS_AWS_MODE=aws` and restart the backend to use the AWS profile."
            )
        else:
            st.success(
                f"Connected to AWS account {result.get('account_id')} "
                f"in {result.get('region')}."
            )
