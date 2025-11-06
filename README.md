# MentorBot

A Telegram bot built with Python and python-telegram-bot library.

## Launch Instructions

Follow these steps to launch the bot:

### Step 1: Install Dependencies

Install the required Python packages by running the following command in your terminal:

```bash
pip install -r requirements.txt
```

### Step 2: Set Up Environment Variables

Create a `.env` file in the project root directory and add your Telegram bot token:

```bash
TELEGRAM_BOT_TOKEN=your_bot_token_here
```

Replace `your_bot_token_here` with your actual Telegram bot token obtained from [@BotFather](https://t.me/BotFather).

### Step 3: Run the Bot

Start the bot by running:

```bash
python main.py
```

The bot will:
- Respond to `/start` command with a greeting
- Echo back any text messages you send

### Step 4: Access the Bot

Once the bot is running, you can interact with it on Telegram:

**Bot Link:** https://t.me/test1_mentorBot

## Project Structure

- `main.py` - Main bot application
- `requirements.txt` - Python dependencies
- `.env` - Environment variables (create this file, not tracked in git)
- `.gitignore` - Git ignore patterns

