***

### 0.15 (2023/09/29)
- Added ability to handle YouTube links.
- Translated README.md to English.

### 0.14 (2022/06/15)
- Fixed an issue where an incorrect value was entered for the OTP Secret Key.

### 0.13 (2021/10/05)
- Added OTP automatic input feature [Setup Guide](#Setting-Up-OTP).
  
- Automatically re-login when disconnected (automatically logs in if 2-step authentication is enabled and DSM_OTP_SECRET is configured).
  
- Added the ability to send failure messages when DSM connection fails.

### 0.12 (2021/07/10)
- Fixed OTP login issue in DSM 7.0.

### 0.11 (2020/10/23)
- Functionality changes for DSM 7.0 or an update to Download Station around October 20, 2020.
  
- Changed file upload to the watch_dir when sending files to Telegram.
  
- Added DSM_WATCH environment variable for the full path of the Torrent Watch directory [Setup Guide](#Setting-Up-Torrent-Watch-Directory).
  
- Modified the notification for "unknown error."

### 0.10 (2020/09/11)
- Fixed issues with Synobot not working on DSM 7.0.
  
- Added the /task command (list of active tasks in Download Station, including ID, name, size, status, downloaded size, upload size, download speed, and upload speed).
  
- Added the /stat command (retrieve network speed information in Download Station, including download speed and upload speed).

### 0.9 (2020/06/02)
- Removed Markdown formatting from Torrent titles in DS Download notifications.

### 0.8 (2020/05/22)
- Fixed an issue where registering received torrent files failed when using private certificates.
  
- Fixed the continuous output of warning logs when using private certificates.
  
- Fixed an issue where deleted task lists were retained.
  
- Added support for localization using the TG_LANG environment variable (ko_kr, en_us). It defaults to ko_kr if not specified.

### 0.7 (2020/05/19)
- Added DSM_AUTO_DEL environment variable. Set to 0 by default. Change it to 1 to enable automatic task deletion upon completion.
  
- Added Download Station automatic deletion feature.

### 0.6 (2020/05/18)
- Fixed an issue where Synobot wouldn't start if the DSM_PW environment variable was missing.
  
- Added the /dslogin command in Telegram (to attempt re-login).
  
- Added support for 2-step authentication (OTP).
  
- Completely changed the login code.
  
- Added the DSM_CERT environment variable (set to 0 when using a certificate with an HTTPS connection).

### 0.5 (2019/09/03)
- Removed Markdown formatting from DS Download notifications.

### 0.4 (2019/08/30)
- Fixed an issue with Torrent titles containing square brackets [].
  
- Fixed issues when deleting during download.

### 0.3
- Prepared for language packs (loading language packs based on SYNO_LANG environment setting).
  
- Fixed duplicate messages when canceling downloads.

### 0.2
- Exception handling for requests.

### 0.1
- Initial version of Synobot.

***

# Synology DSM Download Station Task Monitor and Task Creation for Magnet and Torrent Files

## **Synobot Features**

Synobot provides the following simple features:

1. Telegram notifications for Download Station tasks.
   - Notifications are triggered by:
     - Receiving a task with a size greater than 0.
     - A change in status (e.g., downloading to completed).
     - Deletion of tasks from the list.

2. Magnet link support.
   - Sending magnet links to the Telegram bot will add them to Download Station.

3. Torrent file support.
   - Sending torrent files to the Telegram bot will add them to Download Station.

4. /dslogin command support.
   - Sending the /dslogin command to the Telegram bot will attempt to re-login.

## **Environment Variables for Docker Installation**

When installing Synobot via Docker, you need to set the following environment variable values:

- To receive Telegram alerts, specify the chat IDs of users (use a comma to separate multiple IDs with no spaces).
  - **TG_NOTY_ID** *12345678,87654321*

- Enter your Telegram bot token.
  - **TG_BOT_TOKEN** *186547547:AAEXOA9ld1tlsJXvEVBt4MZYq3bHA1EsJow*

- Specify the chat IDs of users allowed to use Telegram bot commands (use a comma to separate multiple IDs with no spaces).
  - **TG_VALID_USER** *12345678,87654321*

- Enter the DSM login user ID.
  - **DSM_ID** *your_dsm_id*

- Specify the chat ID of the Telegram user who will be asked for a password when logging into Download Station.
  - **TG_DSM_PW_ID** *12345678*

- Enter the DSM URL (include http or https but exclude the port).
  - **DSM_URL** *https://DSM_IP_OR_URL*

  Example: Correct - https://www.dsm.com
  Incorrect - https://www.dsm.com:8000

- Enter the port for Download Station (matching http or https based on DSM_URL).
  - **DS_PORT** *8000*

- Specify the Synobot language pack (currently only supports ko_kr).
  - **SYNO_LANG** *ko_kr*

- Configure the DSM_CERT environment variable (use 0 when using a certificate with an HTTPS connection).
  - **DSM_CERT** *1*

- Enter the value of the secret key for 2-step authentication when configuring DSM 2-step authentication.
  - **DSM_OTP_SECRET** *VFGW*

- Set the timezone for Synobot Docker (use values corresponding to TZ database names).
  - **TZ** *Asia/Seoul*

- Enable Synobot Docker logs to be viewable on the container details log tab.
  - **DOCKER_LOG** *1*

***

**Note: If the DSM_PW environment variable is missing, Synobot Docker will request the DSM login password each time it restarts.**

**Synobot does not store user passwords anywhere.**

**Password messages received by the Telegram bot are deleted immediately.**

If you find entering the password each time inconvenient, add your DSM login password to the DSM_PW environment variable using the "+" button in Docker settings.

- **DSM_PW** *your_dsm_password*

***

For Synology Docker, configure the settings as follows:

![synobot_config_1](https://raw.githubusercontent.com/acidpop/synobot_public/master/img/synobot_config1.png)

![synobot_config_2](https://raw.githubusercontent.com/acidpop/synobot_public/master/img/synobot_config2.png)

![synobot_config_3](https://raw.githubusercontent.com/acidpop/synobot_public/master/img/synobot_config3.png)

***

- Tip

To find the chat ID of a Telegram user:

<a href="https://blog.acidpop.kr/216?category=679730" target="_blank">How to Find Your Chat ID</a>

***

Customizing Synobot's Introduction Message:

1. Log in to DSM terminal with root access using the sudo -i command.

2. Find the Container ID of the currently running Synobot using the docker ps -a command.

3. Access the Docker internals using the docker exec -it {Container ID} /bin/bash command.

4. Run apt-get update.

5. Install vim using apt-get install vim.

6. Open the ko_kr.json file with vim and modify the message as needed.

7. Restart the Synobot Docker.

***

## Setting Up Torrent Watch Directory

To set up the DSM_WATCH environment variable introduced in version 0.11, follow these steps:

1. Click the Advanced Settings button.

![synobot_config_4](https://raw.githubusercontent.com/acidpop/synobot/master/img/synobot_config4.png)

2. Select the Volume tab and click the Add Folder button.

![synobot_config_5](https://raw.githubusercontent.com/acidpop/synobot/master/img/synobot_config5.png)

3. Choose the watch directory you configured in Download Station.

![synobot_config_6](https://raw.githubusercontent.com/acidpop/synobot/master/img/synobot_config6.png)

4. Enter **/tor_watch** in the Mount path.

![synobot_config_7](https://raw.githubusercontent.com/acidpop/synobot/master/img/synobot_config7.png)

5. In the Environment Variable Settings tab, set the value of DSM_WATCH to **/tor_watch**.

![synobot_config_8](https://raw.githubusercontent.com/acidpop/synobot/master/img/synobot_config8.png)

## Setting Up OTP (2-Step Authentication)

To configure the OTP automatic input feature introduced in version 0.13, follow these steps:

1. Click on "Add 2-step verification" in your account settings.

2. If you encounter the QR code scan screen, click "Can't scan it."

![synobot_config_9](https://raw.githubusercontent.com/acidpop/synobot/master/img/synobot_config9.png)

3. Make a note of the secret key value.

![synobot_config_10](https://raw.githubusercontent.com/acidpop/synobot/master/img/synobot_config10.png)

4. In your Synobot Docker settings, enter the secret key value in the DSM_OTP_SECRET environment variable.

***

For inquiries, please use the synobot GitHub repository:

<a href="https://github.com/acidpop/synobot_public" target="_blank">synobot GitHub</a>

