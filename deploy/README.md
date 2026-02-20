# Deploying CodeBot to AWS EC2

This guide outlines the steps to deploy the CodeBot application (Streamlit UI + Webhook Server) to an AWS EC2 instance using Docker Compose.

## Prerequisites

1.  **AWS Account**: Verify you have access to create EC2 instances.
2.  **SSH Key Pair**: Create/Download an SSH key pair (`.pem`) to access your instance.
3.  **Local Git**: Ensure your code is pushed to a git repository.
    > [!IMPORTANT]
    > **Security**: Ensure your `.env` file is in `.gitignore` and is **NOT** pushed to the repository.

## Step 1: Launch EC2 Instance

1.  Go to the **AWS Management Console** -> **EC2**.
2.  Click **Launch Instance**.
3.  **Name**: `CodeBot-Server`
4.  **AMI**: Amazon Linux 2023 AMI (HVM) - Kernel 6.1
5.  **Instance Type**: `t3.medium` (Recommended: 2 vCPU, 4GB RAM) or larger if running local models.
6.  **Key pair**: Select your created key pair.
7.  **Network Settings**:
    - Allow SSH traffic from Anywhere (or your restricted IP).
    - Allow HTTP/HTTPS traffic from the internet.
    - **Edit Security Group**: Add Custom TCP Rules:
        - Port `8501` (Streamlit UI) - Source: Anywhere (`0.0.0.0/0`)
        - Port `8000` (Webhook) - Source: Anywhere (`0.0.0.0/0`)
8.  **Storage**: 20GB gp3.
9.  Click **Launch Instance**.

## Step 2: Setup the Server

1.  SSH into your instance:
    ```bash
    ssh -i "path/to/key.pem" ec2-user@<public-ip-address>
    ```

2.  Copy the setup script and run it, or paste command by command:
    ```bash
    # You can copy the content of deploy/setup_ec2.sh
    nano setup_ec2.sh
    chmod +x setup_ec2.sh
    ./setup_ec2.sh
    ```
    
3.  **Logout and login** again for docker group permission changes to take effect.
    ```bash
    exit
    ssh -i "path/to/key.pem" ec2-user@<public-ip-address>
    ```

## Step 3: Deploy Application

1.  Clone your repository:
    ```bash
    git clone https://github.com/your-username/codebot.git
    cd codebot
    ```

2.  **Securely Transfer .env**:
    Do NOT commit `.env` to git. Instead, create it on the server:
    ```bash
    nano .env
    ```
    Paste your production API keys and save (Ctrl+O, Enter, Ctrl+X).

3.  Build and Run:
    ```bash
    chmod +x deploy/start.sh
    ./deploy/start.sh
    ```

## Step 4: Maintenance

- **Updating the app**:
    ```bash
    chmod +x deploy/update.sh
    ./deploy/update.sh
    ```
- **Viewing Logs**:
    ```bash
    docker compose logs -f
    ```

## Step 5: Configure GitHub Webhook

1.  Go to your GitHub Repository -> **Settings** -> **Webhooks**.
2.  Click **Add webhook**.
3.  **Payload URL**: `http://<public-ip-address>:8000/webhook`
4.  **Content type**: `application/json`
5.  **Secret**: The value of `WEBHOOK_SECRET` in your `.env`.
6.  **Events**: Select "Just the push event".
7.  Click **Add webhook**.
