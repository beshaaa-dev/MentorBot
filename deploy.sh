#!/bin/bash
set -e
cd /root/MentorBot
echo "$(date): Deploy started" >> /root/MentorBot/deploy.log
git pull origin main >> /root/MentorBot/deploy.log 2>&1
.venv/bin/pip install -r requirements.txt --quiet >> /root/MentorBot/deploy.log 2>&1
systemctl restart bot webhook
echo "$(date): Deploy finished" >> /root/MentorBot/deploy.log
