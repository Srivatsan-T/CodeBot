# Deploying CodeBot to AWS EC2

This guide walks you through deploying the `CodeBot` application to an Amazon EC2 instance using the provided scripts.

## Prerequisites

1.  **AWS Account**: You need an active AWS account.
2.  **AWS CLI (Optional)**: Useful for managing resources but not strictly required if using the Console.

## Step 1: Launch an EC2 Instance

1.  Log in to the **AWS Management Console**.
2.  Navigate to **EC2** and click **Launch Instance**.
3.  **Name**: `CodeBot-Server`
4.  **AMI**: Select **Amazon Linux 2023 AMI** (Default).
5.  **Instance Type**: `t2.small` or `t3.small` (Recommended). `t2.micro` might run out of memory during builds.
6.  **Key Pair**: Create a new key pair (e.g., `codebot-key`) and download the `.pem` file.
7.  **Network Settings**:
    *   **Allow SSH traffic** from `My IP` (for security).
    *   **Allow HTTP/HTTPS** traffic from the internet.
8.  **Configure Storage**: 8 GB (default) is usually fine, but 16 GB is safer for Docker builds.
9.  Click **Launch Instance**.

## Step 2: Configure Security Group

1.  Go to the **Security Groups** of your created instance.
2.  Edit **Inbound Rules**.
3.  Add the following rules:
    *   **Type**: `Custom TCP`, **Port**: `8501`, **Source**: `0.0.0.0/0` (Streamlit UI)
    *   **Type**: `Custom TCP`, **Port**: `8000`, **Source**: `0.0.0.0/0` (Webhook Server)
    *   **Type**: `SSH`, **Port**: `22`, **Source**: `My IP` (Already set)
4.  Save rules.

## Step 3: Connect to the Instance

Open your terminal (or PowerShell) and navigate to where your `.pem` key is located.

```bash
# Set permissions for key (Linux/Mac only, Windows users skip this)
chmod 400 codebot-key.pem

# SSH into the server
ssh -i "codebot-key.pem" ec2-user@<YOUR-EC2-PUBLIC-IP>
```

## Step 4: Clone the Repository

Once inside the EC2 instance, first ensure Git is installed, then clone the repository:

```bash
# Install Git
sudo dnf install git -y

# Clone the repository
git clone -b master https://github.com/Srivatsan-T/CodeBot.git
cd CodeBot
```

*Note: The Docker configuration files are located in the `deploy/` directory.*

## Step 5: Run Setup

Run the foundational setup script. This installs Docker, Git, and configures the environment.

```bash
chmod +x deploy/setup.sh
./deploy/setup.sh
```

**IMPORTANT**: After this script finishes, you MUST **logout and log back in** for the user permission changes to take effect.

```bash
exit
ssh -i "codebot-key.pem" ec2-user@<YOUR-EC2-PUBLIC-IP>
cd CodeBot
```

## Step 7: Deploy

Run the deployment script to build and start the application.

```bash
chmod +x deploy/deploy.sh
./deploy/deploy.sh
```

## Step 8: Access the Application

*   **UI**: `http://<YOUR-EC2-PUBLIC-IP>:8501`
*   **Webhook**: `http://<YOUR-EC2-PUBLIC-IP>:8000`

**Important**: When you first load the UI, look for the **"Bedrock API Key"** field in the sidebar. Enter your AWS Access Key ID (or configured Secret Key) there to enable the AI features.


## Updating the Application

To update the app in the future (after pushing changes to GitHub):

1.  SSH into the server.
2.  Navigate to the folder: `cd CodeBot`
3.  Run the deploy script: `./deploy/deploy.sh`
