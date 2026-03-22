import logging
import sqlite3
import random
import asyncio
import string
import os
import sys
import re
from datetime import datetime, timedelta
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from pyrogram.errors import FloodWait, UserNotParticipant

# ============================================
# CONFIGURATION
# ============================================

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration - Only BOT_TOKEN from environment, others hardcoded
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SUPPORT_GROUP = -1003849384285
SUPPORT_GROUP_LINK = "https://t.me/ZenitsuXGrabbersupport"
OWNER_ID = 8472389760

if not BOT_TOKEN:
    raise ValueError("No BOT_TOKEN environment variable set")

# Initialize bot
app = Client("character_bot", bot_token=BOT_TOKEN)

# ============================================
# DATABASE SETUP
# ============================================

def init_db():
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Users table
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, username TEXT, thunder_coins INTEGER DEFAULT 0,
                      lightning_crystals INTEGER DEFAULT 0, last_daily TEXT, last_weekly TEXT,
                      last_claim TEXT, last_marry TEXT, last_slot TEXT, role TEXT DEFAULT 'user', 
                      total_chars INTEGER DEFAULT 0)''')
        
        # Characters table
        c.execute('''CREATE TABLE IF NOT EXISTS characters
                     (char_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, anime TEXT,
                      rarity_num INTEGER, media_id TEXT, added_by INTEGER, added_date TEXT)''')
        
        # User characters table
        c.execute('''CREATE TABLE IF NOT EXISTS user_chars
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, char_id INTEGER,
                      is_favorite INTEGER DEFAULT 0, married_to INTEGER DEFAULT NULL,
                      acquired_date TEXT)''')
        
        # Redeem codes table
        c.execute('''CREATE TABLE IF NOT EXISTS redeem_codes
                     (code_id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE, 
                      code_type TEXT, char_id INTEGER, amount INTEGER, uses INTEGER,
                      used_count INTEGER DEFAULT 0, created_by INTEGER, created_date TEXT)''')
        
        # Auction makers table
        c.execute('''CREATE TABLE IF NOT EXISTS auction_makers
                     (user_id INTEGER PRIMARY KEY, username TEXT, added_by INTEGER, added_date TEXT)''')
        
        # Auction history table
        c.execute('''CREATE TABLE IF NOT EXISTS auction_history
                     (auction_id INTEGER PRIMARY KEY AUTOINCREMENT, char_name TEXT, char_rarity TEXT, 
                      char_id INTEGER, seller_id INTEGER, seller_name TEXT, winner_id INTEGER, 
                      winner_name TEXT, final_bid INTEGER, end_time TEXT)''')
        
        # Active auctions table
        c.execute('''CREATE TABLE IF NOT EXISTS active_auctions
                     (auction_id INTEGER PRIMARY KEY AUTOINCREMENT, char_name TEXT, char_rarity TEXT,
                      char_id INTEGER, seller_id INTEGER, seller_name TEXT, current_bid INTEGER,
                      current_bidder_id INTEGER, current_bidder_name TEXT, end_time TEXT, 
                      min_bid INTEGER, status TEXT DEFAULT 'active')''')
        
        # Character drops table
        c.execute('''CREATE TABLE IF NOT EXISTS char_drops
                     (drop_id INTEGER PRIMARY KEY AUTOINCREMENT, char_id INTEGER, message_id INTEGER,
                      chat_id INTEGER, drop_time TEXT, grabbed_by INTEGER DEFAULT NULL,
                      status TEXT DEFAULT 'active')''')
        
        # Slots history table
        c.execute('''CREATE TABLE IF NOT EXISTS slots_history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, result TEXT,
                      win_amount INTEGER, jackpot INTEGER DEFAULT 0, timestamp TEXT)''')
        
        # Insert owner if not exists
        c.execute("INSERT OR IGNORE INTO users (user_id, username, role) VALUES (?, ?, 'owner')",
                  (OWNER_ID, "Owner"))
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully")
    except Exception as e:
        logger.error(f"❌ Database initialization error: {e}")

# ============================================
# CONSTANTS
# ============================================

# 11 Rarities
RARITIES = {
    1: {"name": "Common", "emoji": "🌍"},
    2: {"name": "Rare", "emoji": "☀️"},
    3: {"name": "Epic", "emoji": "🏞️"},
    4: {"name": "Legendary", "emoji": "✨"},
    5: {"name": "Halloween", "emoji": "🎃"},
    6: {"name": "Summer", "emoji": "🌡️"},
    7: {"name": "Winter", "emoji": "❄️"},
    8: {"name": "Autumn", "emoji": "🍁"},
    9: {"name": "Love", "emoji": "💝"},
    10: {"name": "God", "emoji": "👼"},
    11: {"name": "Demon", "emoji": "👿"}
}

# Cooldown times (in seconds)
COOLDOWNS = {
    "daily": 24 * 60 * 60,
    "weekly": 7 * 24 * 60 * 60,
    "claim": 24 * 60 * 60,
    "marry": 30 * 60,
    "slot": 10  # 10 seconds cooldown for slot
}

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_rarity_by_num(num):
    """Get rarity name and emoji by number"""
    return RARITIES.get(num, {"name": "Unknown", "emoji": "❓"})

def is_support_group(chat_id):
    """Check if message is from support group"""
    return str(chat_id) == str(SUPPORT_GROUP)

def get_user_role(user_id):
    """Get user role from database"""
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        c.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result[0] if result else 'user'
    except Exception as e:
        logger.error(f"Error getting user role: {e}")
        return 'user'

def is_owner(user_id):
    """Check if user is owner"""
    return user_id in OWNER_IDS

def is_sudo(user_id):
    """Check if user is sudo"""
    role = get_user_role(user_id)
    return role in ['sudo', 'owner']

def is_uploader(user_id):
    """Check if user is uploader"""
    role = get_user_role(user_id)
    return role in ['uploader', 'sudo', 'owner']

def is_auction_maker(user_id):
    """Check if user is auction maker"""
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        c.execute("SELECT user_id FROM auction_makers WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Error checking auction maker: {e}")
        return False

def generate_redeem_code(code_type, length=10):
    """Generate unique redeem code"""
    chars = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=length))

async def download_media(message):
    """Download media from message"""
    try:
        if message.photo:
            return await message.download(in_memory=True)
        elif message.video:
            return await message.download(in_memory=True)
    except Exception as e:
        logger.error(f"Error downloading media: {e}")
    return None

def get_user_stats(user_id):
    """Get user statistics"""
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        c.execute("SELECT thunder_coins, lightning_crystals FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        c.execute("SELECT COUNT(*) FROM user_chars WHERE user_id = ?", (user_id,))
        total_chars = c.fetchone()[0]
        c.execute("""SELECT c.name, c.rarity_num, c.char_id FROM user_chars uc 
                     JOIN characters c ON uc.char_id = c.char_id 
                     WHERE uc.user_id = ? AND uc.is_favorite = 1""", (user_id,))
        fav = c.fetchone()
        conn.close()
        return user, total_chars, fav
    except Exception as e:
        logger.error(f"Error getting user stats: {e}")
        return None, 0, None

def get_user_chars_page(user_id, page=1, per_page=10):
    """Get paginated user characters"""
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        offset = (page - 1) * per_page
        c.execute("""SELECT c.name, c.rarity_num, c.char_id, uc.is_favorite
                     FROM user_chars uc JOIN characters c ON uc.char_id = c.char_id
                     WHERE uc.user_id = ?
                     ORDER BY uc.is_favorite DESC, c.char_id
                     LIMIT ? OFFSET ?""", (user_id, per_page, offset))
        chars = c.fetchall()
        c.execute("SELECT COUNT(*) FROM user_chars WHERE user_id = ?", (user_id,))
        total = c.fetchone()[0]
        conn.close()
        return chars, total
    except Exception as e:
        logger.error(f"Error getting user chars: {e}")
        return [], 0

def find_chars_page(search_term, page=1, per_page=10):
    """Search characters with pagination"""
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        offset = (page - 1) * per_page
        c.execute("""SELECT char_id, name, anime, rarity_num 
                     FROM characters WHERE name LIKE ? OR anime LIKE ?
                     ORDER BY char_id LIMIT ? OFFSET ?""", 
                  (f'%{search_term}%', f'%{search_term}%', per_page, offset))
        chars = c.fetchall()
        c.execute("""SELECT COUNT(*) FROM characters WHERE name LIKE ? OR anime LIKE ?""", 
                  (f'%{search_term}%', f'%{search_term}%'))
        total = c.fetchone()[0]
        conn.close()
        return chars, total
    except Exception as e:
        logger.error(f"Error finding chars: {e}")
        return [], 0

def check_user_has_char(user_id, char_id):
    """Check if user owns a character"""
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        c.execute("SELECT id FROM user_chars WHERE user_id = ? AND char_id = ?", (user_id, char_id))
        result = c.fetchone()
        conn.close()
        return result is not None
    except Exception as e:
        logger.error(f"Error checking user char: {e}")
        return False

def get_cooldown_time(last_time, cooldown_seconds):
    """Get remaining cooldown time"""
    if not last_time:
        return 0
    try:
        last = datetime.fromisoformat(last_time)
        elapsed = (datetime.now() - last).total_seconds()
        remaining = cooldown_seconds - elapsed
        return max(0, int(remaining))
    except:
        return 0

def format_cooldown(seconds):
    """Format cooldown time"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        return f"{seconds // 3600}h"
    else:
        return f"{seconds // 86400}d"

# ============================================
# GROUP CHECK DECORATOR
# ============================================

def group_only(func):
    """Decorator to restrict commands to support group"""
    async def wrapper(client, message):
        try:
            if not is_support_group(message.chat.id):
                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("📢 Join Support Group", url=SUPPORT_GROUP_LINK)
                ]])
                await message.reply_text(
                    "❌ This command can only be used in the support group!\n"
                    "Click the button below to join and use commands.",
                    reply_markup=keyboard
                )
                return
            return await func(client, message)
        except Exception as e:
            logger.error(f"Error in group_only decorator: {e}")
            await message.reply_text("❌ An error occurred. Please try again.")
    return wrapper

# Initialize database
init_db()

# ============================================
# BACKGROUND TASKS
# ============================================

async def char_drop_system():
    """Character drop system - runs every 2 hours"""
    while True:
        try:
            await asyncio.sleep(7200)  # 2 hours
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            c.execute("""SELECT char_id, name, anime, rarity_num, media_id 
                         FROM characters WHERE rarity_num BETWEEN 1 AND 4 
                         ORDER BY RANDOM() LIMIT 1""")
            char = c.fetchone()
            
            if not char:
                conn.close()
                continue
                
            char_id, name, anime, rarity_num, media_id = char
            rarity = get_rarity_by_num(rarity_num)
            
            drop_text = (
                f"🎁 **Character Drop!** 🎁\n\n"
                f"✨ **Name:** {name}\n"
                f"📺 **Anime:** {anime}\n"
                f"⭐ **Rarity:** {rarity['name']} {rarity['emoji']}\n"
                f"🆔 **ID:** {char_id}\n\n"
                f"Type `/grab` to grab this character!"
            )
            
            if media_id:
                msg = await app.send_photo(
                    chat_id=SUPPORT_GROUP,
                    photo=media_id,
                    caption=drop_text
                )
            else:
                msg = await app.send_message(
                    chat_id=SUPPORT_GROUP,
                    text=drop_text
                )
            
            c.execute("""INSERT INTO char_drops (char_id, message_id, chat_id, drop_time, status)
                         VALUES (?, ?, ?, ?, 'active')""",
                      (char_id, msg.id, SUPPORT_GROUP, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            
            logger.info(f"Character dropped: {name} (ID: {char_id})")
            
        except Exception as e:
            logger.error(f"Drop system error: {e}")

async def process_auction_end(auction_id):
    """Process auction end - give character to winner"""
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("""SELECT char_name, char_rarity, char_id, seller_id, seller_name,
                          current_bid, current_bidder_id, current_bidder_name
                     FROM active_auctions WHERE auction_id = ?""", (auction_id,))
        auction = c.fetchone()
        
        if not auction:
            conn.close()
            return
            
        (char_name, char_rarity, char_id, seller_id, seller_name,
         final_bid, winner_id, winner_name) = auction
        
        if winner_id:
            # Give character to winner
            c.execute("""INSERT INTO user_chars (user_id, char_id, acquired_date)
                         VALUES (?, ?, ?)""",
                      (winner_id, char_id, datetime.now().isoformat()))
            c.execute("UPDATE users SET total_chars = total_chars + 1 WHERE user_id = ?", (winner_id,))
            
            # Give crystals to seller
            c.execute("UPDATE users SET lightning_crystals = lightning_crystals + ? WHERE user_id = ?",
                      (final_bid, seller_id))
            
            # Save to history
            c.execute("""INSERT INTO auction_history 
                         (char_name, char_rarity, char_id, seller_id, seller_name,
                          winner_id, winner_name, final_bid, end_time)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (char_name, char_rarity, char_id, seller_id, seller_name,
                       winner_id, winner_name or f"User {winner_id}", final_bid, 
                       datetime.now().isoformat()))
            
            # Notify winner
            try:
                await app.send_message(
                    winner_id,
                    f"🎉 **You Won the Auction!** 🎉\n\n"
                    f"✨ **Character:** {char_name} {char_rarity}\n"
                    f"🆔 **ID:** {char_id}\n"
                    f"💰 **Final Bid:** {final_bid:,} 🔮\n\n"
                    f"Character has been added to your harem!"
                )
            except:
                pass
            
            # Notify seller
            try:
                await app.send_message(
                    seller_id,
                    f"💰 **Auction Sold!** 💰\n\n"
                    f"✨ **Character:** {char_name} {char_rarity}\n"
                    f"🆔 **ID:** {char_id}\n"
                    f"💰 **Sold For:** {final_bid:,} 🔮\n"
                    f"👤 **Winner:** {winner_name or f'User {winner_id}'}\n\n"
                    f"Crystals added to your balance!"
                )
            except:
                pass
                
        else:
            # No bids - return character to seller
            c.execute("""INSERT INTO user_chars (user_id, char_id, acquired_date)
                         VALUES (?, ?, ?)""",
                      (seller_id, char_id, datetime.now().isoformat()))
            c.execute("UPDATE users SET total_chars = total_chars + 1 WHERE user_id = ?", (seller_id,))
            
            # Notify seller
            try:
                await app.send_message(
                    seller_id,
                    f"📢 **Auction Expired** 📢\n\n"
                    f"✨ **Character:** {char_name} {char_rarity}\n"
                    f"🆔 **ID:** {char_id}\n"
                    f"❌ No bids were received.\n\n"
                    f"Character returned to your harem!"
                )
            except:
                pass
        
        # Remove from active auctions
        c.execute("DELETE FROM active_auctions WHERE auction_id = ?", (auction_id,))
        
        # Clean old history (keep last 10, delete after 5 days)
        cutoff = (datetime.now() - timedelta(days=5)).isoformat()
        c.execute("DELETE FROM auction_history WHERE end_time < ?", (cutoff,))
        
        c.execute("""SELECT auction_id FROM auction_history 
                     ORDER BY end_time DESC LIMIT -1 OFFSET 10""")
        for row in c.fetchall():
            c.execute("DELETE FROM auction_history WHERE auction_id = ?", (row[0],))
        
        conn.commit()
        conn.close()
        
        logger.info(f"Auction {auction_id} processed successfully")
        
    except Exception as e:
        logger.error(f"Error processing auction end: {e}")

async def check_auction_ends():
    """Check for ended auctions every minute"""
    while True:
        try:
            await asyncio.sleep(60)
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("SELECT auction_id FROM active_auctions WHERE end_time < ?", 
                      (datetime.now().isoformat(),))
            ended = c.fetchall()
            conn.close()
            
            for auction in ended:
                await process_auction_end(auction[0])
                
        except Exception as e:
            logger.error(f"Error checking auction ends: {e}")

# ============================================
# COMMAND HANDLERS - 38 COMMANDS
# ============================================

# 1. /start
@app.on_message(filters.command("start"))
async def start_command(client, message):
    try:
        user_id = message.from_user.id
        username = message.from_user.first_name
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        c.execute("INSERT OR IGNORE INTO users (user_id, username, role) VALUES (?, ?, 'user')", 
                  (user_id, username))
        conn.commit()
        conn.close()
        
        welcome_text = (
            f"👋 **Welcome {username}!**\n\n"
            f"I'm a **Character Collection Bot** where you can:\n"
            f"• Collect rare characters 🎴\n"
            f"• Trade in auctions 🏷️\n"
            f"• Play slot machine 🎰\n"
            f"• Marry characters 💞\n\n"
            f"Use `/help` to see all commands!"
        )
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Join Support Group", url=SUPPORT_GROUP_LINK)
        ]])
        
        await message.reply_text(welcome_text, reply_markup=keyboard)
        logger.info(f"User started: {username} (ID: {user_id})")
        
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 2. /profile
@app.on_message(filters.command("profile"))
@group_only
async def profile_command(client, message):
    try:
        user_id = message.from_user.id
        username = message.from_user.first_name
        
        user, total_chars, fav = get_user_stats(user_id)
        
        if not user:
            await message.reply_text("❌ You need to start the bot first using /start")
            return
            
        coins, crystals = user
        fav_text = "None"
        
        if fav:
            rarity = get_rarity_by_num(fav[1])
            fav_text = f"{fav[0]} {rarity['emoji']} [ID: {fav[2]}]"
        
        profile_text = (
            f"👤 **User Profile**\n"
            f"────────────────\n"
            f"**Username:** {username}\n"
            f"**Thunder Coins ⚡:** {coins:,}\n"
            f"**Lightning Crystals 🔮:** {crystals:,}\n"
            f"**Harem Size:** {total_chars}\n"
            f"**Favorite:** {fav_text}\n"
            f"────────────────"
        )
        
        await message.reply_text(profile_text)
        
    except Exception as e:
        logger.error(f"Error in profile command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 3. /balance
@app.on_message(filters.command("balance"))
@group_only
async def balance_command(client, message):
    try:
        user_id = message.from_user.id
        user, _, _ = get_user_stats(user_id)
        
        if not user:
            await message.reply_text("❌ You need to start the bot first using /start")
            return
            
        coins, crystals = user
        
        balance_text = (
            f"💰 **Your Balance**\n"
            f"────────────────\n"
            f"**Thunder Coins ⚡:** `{coins:,}`\n"
            f"**Lightning Crystals 🔮:** `{crystals:,}`\n"
            f"────────────────"
        )
        
        await message.reply_text(balance_text)
        
    except Exception as e:
        logger.error(f"Error in balance command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 4. /daily
@app.on_message(filters.command("daily"))
@group_only
async def daily_command(client, message):
    try:
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("SELECT last_daily FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if result and result[0]:
            remaining = get_cooldown_time(result[0], COOLDOWNS["daily"])
            if remaining > 0:
                await message.reply_text(
                    f"❌ **Daily already claimed!**\n"
                    f"⏰ **Cooldown:** `{format_cooldown(remaining)}`\n"
                    f"Come back later!"
                )
                conn.close()
                return
        
        c.execute("""UPDATE users SET 
                     thunder_coins = thunder_coins + 10000, 
                     last_daily = ? 
                     WHERE user_id = ?""", 
                  (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"✅ **Daily Claimed!**\n"
            f"────────────────\n"
            f"You received **10,000 Thunder Coins ⚡**!\n"
            f"Come back in 24 hours for more!\n"
            f"────────────────"
        )
        
        logger.info(f"User {user_id} claimed daily")
        
    except Exception as e:
        logger.error(f"Error in daily command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 5. /weekly
@app.on_message(filters.command("weekly"))
@group_only
async def weekly_command(client, message):
    try:
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("SELECT last_weekly FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if result and result[0]:
            remaining = get_cooldown_time(result[0], COOLDOWNS["weekly"])
            if remaining > 0:
                await message.reply_text(
                    f"❌ **Weekly already claimed!**\n"
                    f"⏰ **Cooldown:** `{format_cooldown(remaining)}`\n"
                    f"Come back later!"
                )
                conn.close()
                return
        
        c.execute("""UPDATE users SET 
                     thunder_coins = thunder_coins + 100000, 
                     last_weekly = ? 
                     WHERE user_id = ?""", 
                  (datetime.now().isoformat(), user_id))
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"✅ **Weekly Claimed!**\n"
            f"────────────────\n"
            f"You received **100,000 Thunder Coins ⚡**!\n"
            f"Come back in 7 days for more!\n"
            f"────────────────"
        )
        
        logger.info(f"User {user_id} claimed weekly")
        
    except Exception as e:
        logger.error(f"Error in weekly command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 6. /claim
@app.on_message(filters.command("claim"))
@group_only
async def claim_command(client, message):
    try:
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("SELECT last_claim FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if result and result[0]:
            remaining = get_cooldown_time(result[0], COOLDOWNS["claim"])
            if remaining > 0:
                await message.reply_text(
                    f"❌ **Daily character already claimed!**\n"
                    f"⏰ **Cooldown:** `{format_cooldown(remaining)}`\n"
                    f"Come back later!"
                )
                conn.close()
                return
        
        # Get random common character
        c.execute("""SELECT char_id, name, anime, media_id FROM characters 
                     WHERE rarity_num = 1 ORDER BY RANDOM() LIMIT 1""")
        char = c.fetchone()
        
        if not char:
            await message.reply_text("❌ No common characters available yet!")
            conn.close()
            return
            
        char_id, name, anime, media_id = char
        
        # Add character to user
        c.execute("""INSERT INTO user_chars (user_id, char_id, acquired_date) 
                     VALUES (?, ?, ?)""", 
                  (user_id, char_id, datetime.now().isoformat()))
        
        c.execute("""UPDATE users SET 
                     last_claim = ?, 
                     total_chars = total_chars + 1 
                     WHERE user_id = ?""", 
                  (datetime.now().isoformat(), user_id))
        
        conn.commit()
        conn.close()
        
        rarity = get_rarity_by_num(1)
        
        claim_text = (
            f"🎉 **Character Claimed!**\n"
            f"────────────────\n"
            f"✨ **Name:** {name}\n"
            f"📺 **Anime:** {anime}\n"
            f"⭐ **Rarity:** {rarity['name']} {rarity['emoji']}\n"
            f"🆔 **ID:** {char_id}\n"
            f"────────────────\n"
            f"Use `/harem` to view your collection!"
        )
        
        if media_id:
            await message.reply_photo(photo=media_id, caption=claim_text)
        else:
            await message.reply_text(claim_text)
            
        logger.info(f"User {user_id} claimed character {name} (ID: {char_id})")
        
    except Exception as e:
        logger.error(f"Error in claim command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 7. /exchange
@app.on_message(filters.command("exchange"))
@group_only
async def exchange_command(client, message):
    try:
        user_id = message.from_user.id
        args = message.text.split()
        
        if len(args) != 2:
            await message.reply_text(
                "❌ **Usage:** `/exchange <amount>`\n"
                "Example: `/exchange 500` (500 ⚡ → 5 🔮)"
            )
            return
        
        try:
            amount = int(args[1])
            if amount < 100 or amount % 100 != 0:
                await message.reply_text("❌ Amount must be multiples of 100")
                return
        except ValueError:
            await message.reply_text("❌ Invalid amount!")
            return
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("SELECT thunder_coins FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if not result or result[0] < amount:
            await message.reply_text("❌ You don't have enough Thunder Coins!")
            conn.close()
            return
        
        crystals = amount // 100
        
        c.execute("""UPDATE users SET 
                     thunder_coins = thunder_coins - ?, 
                     lightning_crystals = lightning_crystals + ? 
                     WHERE user_id = ?""", 
                  (amount, crystals, user_id))
        
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"✅ **Exchange Successful!**\n"
            f"────────────────\n"
            f"**Exchanged:** `{amount:,} ⚡`\n"
            f"**Received:** `{crystals:,} 🔮`\n"
            f"────────────────"
        )
        
        logger.info(f"User {user_id} exchanged {amount} ⚡ for {crystals} 🔮")
        
    except Exception as e:
        logger.error(f"Error in exchange command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 8. /gift
@app.on_message(filters.command("gift"))
@group_only
async def gift_command(client, message):
    try:
        user_id = message.from_user.id
        sender_name = message.from_user.first_name
        
        # Case 1: Replying to a user with character ID
        if message.reply_to_message:
            target_id = message.reply_to_message.from_user.id
            if len(message.command) < 2:
                await message.reply_text(
                    "❌ **Usage:** Reply to user with `/gift <character_id>`\n"
                    "Example: Reply to a user and type `/gift 8`"
                )
                return
            try:
                char_id = int(message.command[1])
            except ValueError:
                await message.reply_text("❌ Invalid character ID! Use numbers like 1, 2, 3...")
                return
        
        # Case 2: Using user_id and character ID
        elif len(message.command) >= 3:
            try:
                target_id = int(message.command[1])
                char_id = int(message.command[2])
            except ValueError:
                await message.reply_text("❌ Invalid user ID or character ID! Use numbers only.")
                return
        
        else:
            await message.reply_text(
                "❌ **Usage:**\n"
                "• `/gift <user_id> <character_id>`\n"
                "• Reply to user with `/gift <character_id>`"
            )
            return
        
        # Don't allow gifting to self
        if target_id == user_id:
            await message.reply_text("❌ You cannot gift a character to yourself!")
            return
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Check if character exists and belongs to sender
        c.execute("""SELECT uc.id, c.name, c.rarity_num FROM user_chars uc
                     JOIN characters c ON uc.char_id = c.char_id
                     WHERE uc.char_id = ? AND uc.user_id = ?""",
                  (char_id, user_id))
        char = c.fetchone()
        
        if not char:
            await message.reply_text("❌ Character not found or doesn't belong to you!")
            conn.close()
            return
        
        # Check if target user exists
        c.execute("SELECT user_id, username FROM users WHERE user_id = ?", (target_id,))
        target_user = c.fetchone()
        
        if not target_user:
            try:
                target = await client.get_users(target_id)
                target_name = target.first_name
                c.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", 
                         (target_id, target_name))
            except:
                await message.reply_text("❌ Target user not found!")
                conn.close()
                return
        else:
            target_name = target_user[1]
        
        char_name = char[1]
        rarity = get_rarity_by_num(char[2])
        
        # Transfer character
        c.execute("UPDATE user_chars SET user_id = ? WHERE char_id = ? AND user_id = ?", 
                 (target_id, char_id, user_id))
        c.execute("UPDATE users SET total_chars = total_chars - 1 WHERE user_id = ?", (user_id,))
        c.execute("UPDATE users SET total_chars = total_chars + 1 WHERE user_id = ?", (target_id,))
        
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"✅ **Gift Sent!**\n"
            f"────────────────\n"
            f"🎴 **Character:** {char_name} {rarity['emoji']} [ID: {char_id}]\n"
            f"👤 **From:** {sender_name}\n"
            f"👤 **To:** {target_name}\n"
            f"────────────────\n"
            f"Character transferred successfully!"
        )
        
        # Notify the recipient
        try:
            await client.send_message(
                target_id,
                f"🎁 **You Received a Gift!**\n"
                f"────────────────\n"
                f"👤 **From:** {sender_name}\n"
                f"🎴 **Character:** {char_name} {rarity['emoji']} [ID: {char_id}]\n"
                f"────────────────\n"
                f"Check your `/harem` to view it!"
            )
        except:
            pass
            
        logger.info(f"User {user_id} gifted character {char_id} to {target_id}")
        
    except Exception as e:
        logger.error(f"Error in gift command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 9. /harem
@app.on_message(filters.command("harem"))
@group_only
async def harem_command(client, message):
    try:
        user_id = message.from_user.id
        page = 1
        
        if len(message.command) > 1:
            try:
                page = int(message.command[1])
            except ValueError:
                pass
        
        chars, total = get_user_chars_page(user_id, page)
        
        if not chars:
            await message.reply_text("❌ Your harem is empty! Grab some characters first.")
            return
        
        # Get favorite char media for preview
        fav_media = None
        for char in chars:
            if char[3] == 1:  # is_favorite
                conn = sqlite3.connect('character_bot.db')
                c = conn.cursor()
                c.execute("SELECT media_id FROM characters WHERE char_id = ?", (char[2],))
                media = c.fetchone()
                conn.close()
                if media and media[0]:
                    fav_media = media[0]
                    break
        
        total_pages = ((total - 1) // 10) + 1
        
        text = f"🎴 **Your Harem** (Page {page}/{total_pages}) 🎴\n\n"
        
        for i, char in enumerate(chars, 1):
            name, rarity_num, char_id, is_fav = char
            rarity = get_rarity_by_num(rarity_num)
            fav_star = "⭐ " if is_fav else ""
            text += f"{fav_star}{i}. **{name}** {rarity['emoji']} [ID: {char_id}]\n"
        
        # Create pagination buttons
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"harem_{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"harem_{page+1}"))
        
        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        
        if fav_media:
            await message.reply_photo(photo=fav_media, caption=text, reply_markup=keyboard)
        else:
            await message.reply_text(text, reply_markup=keyboard)
            
    except Exception as e:
        logger.error(f"Error in harem command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 10. /find
@app.on_message(filters.command("find"))
@group_only
async def find_command(client, message):
    try:
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/find <character name>`\nExample: `/find Gojo`")
            return
        
        search_term = ' '.join(message.command[1:])
        page = 1
        
        chars, total = find_chars_page(search_term, page)
        
        if not chars:
            await message.reply_text(f"❌ No characters found for '{search_term}'")
            return
        
        total_pages = ((total - 1) // 10) + 1
        
        text = f"🔍 **Results for:** '{search_term}' (Page {page}/{total_pages})\n"
        text += "─" * 30 + "\n"
        
        for i, char in enumerate(chars, 1):
            char_id, name, anime, rarity_num = char
            rarity = get_rarity_by_num(rarity_num)
            text += f"{i}. **{name}** {rarity['emoji']} [ID: {char_id}]\n"
        
        # Create pagination buttons
        buttons = []
        if page > 1:
            buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"find_{search_term}_{page-1}"))
        if page < total_pages:
            buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"find_{search_term}_{page+1}"))
        
        keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
        
        await message.reply_text(text, reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error in find command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 11. /cfind
@app.on_message(filters.command("cfind"))
@group_only
async def cfind_command(client, message):
    try:
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/cfind <character_id>`\nExample: `/cfind 8`")
            return
        
        try:
            char_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ Invalid ID! Use numbers like 1, 2, 3...")
            return
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("SELECT name, anime, rarity_num, media_id FROM characters WHERE char_id = ?", (char_id,))
        char = c.fetchone()
        conn.close()
        
        if not char:
            await message.reply_text("❌ Character not found!")
            return
        
        name, anime, rarity_num, media_id = char
        rarity = get_rarity_by_num(rarity_num)
        
        text = (
            f"🎴 **Name:** {name}\n"
            f"🃏 **Rarity:** {rarity['name']} {rarity['emoji']}\n"
            f"🪪 **ID:** {char_id}"
        )
        
        if media_id:
            await message.reply_photo(photo=media_id, caption=text)
        else:
            await message.reply_text(text)
            
    except Exception as e:
        logger.error(f"Error in cfind command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 12. /fav
@app.on_message(filters.command("fav"))
@group_only
async def fav_command(client, message):
    try:
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/fav <character_id>`\nExample: `/fav 8`")
            return
        
        try:
            char_id = int(message.command[1])
        except ValueError:
            await message.reply_text("❌ Invalid ID! Use numbers like 1, 2, 3...")
            return
        
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Check if character exists and belongs to user
        c.execute("SELECT id FROM user_chars WHERE char_id = ? AND user_id = ?", (char_id, user_id))
        if not c.fetchone():
            await message.reply_text("❌ Character not found in your harem!")
            conn.close()
            return
        
        # Get character name for response
        c.execute("SELECT name FROM characters WHERE char_id = ?", (char_id,))
        char_name = c.fetchone()[0]
        
        # Remove favorite from all other characters
        c.execute("UPDATE user_chars SET is_favorite = 0 WHERE user_id = ?", (user_id,))
        
        # Set new favorite
        c.execute("UPDATE user_chars SET is_favorite = 1 WHERE char_id = ? AND user_id = ?", 
                 (char_id, user_id))
        
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"✅ **Favorite Set!**\n"
            f"────────────────\n"
            f"**{char_name}** [ID: {char_id}] is now your favorite!\n"
            f"────────────────"
        )
        
    except Exception as e:
        logger.error(f"Error in fav command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 13. /unfav
@app.on_message(filters.command("unfav"))
@group_only
async def unfav_command(client, message):
    try:
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("UPDATE user_chars SET is_favorite = 0 WHERE user_id = ?", (user_id,))
        
        conn.commit()
        conn.close()
        
        await message.reply_text("✅ **Favorite Removed!**")
        
    except Exception as e:
        logger.error(f"Error in unfav command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 14. /top
@app.on_message(filters.command("top"))
@group_only
async def top_command(client, message):
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("""SELECT username, total_chars FROM users 
                     WHERE total_chars > 0 
                     ORDER BY total_chars DESC LIMIT 10""")
        top = c.fetchall()
        conn.close()
        
        if not top:
            await message.reply_text("📊 No collectors yet!")
            return
        
        text = "🏆 **Top Collectors** 🏆\n\n"
        for i, (name, count) in enumerate(top, 1):
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "📌"
            text += f"{medal} **{i}.** {name} — `{count}` characters\n"
        
        await message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error in top command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 15. /marry
@app.on_message(filters.command("marry"))
@group_only
async def marry_command(client, message):
    try:
        user_id = message.from_user.id
        username = message.from_user.first_name
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Check cooldown
        c.execute("SELECT last_marry FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if result and result[0]:
            remaining = get_cooldown_time(result[0], COOLDOWNS["marry"])
            if remaining > 0:
                await message.reply_text(
                    f"❌ **Marriage on cooldown!**\n"
                    f"⏰ **Wait:** `{format_cooldown(remaining)}`\n"
                    f"Come back later!"
                )
                conn.close()
                return
        
        # Get a random Common (1) or Rare (2) character from user's harem
        c.execute("""SELECT uc.char_id, c.name, c.rarity_num FROM user_chars uc
                     JOIN characters c ON uc.char_id = c.char_id
                     WHERE uc.user_id = ? AND c.rarity_num IN (1, 2)
                     ORDER BY RANDOM() LIMIT 1""", (user_id,))
        char = c.fetchone()
        
        if not char:
            await message.reply_text(
                "❌ **No eligible characters!**\n"
                "You need Common or Rare characters to marry."
            )
            conn.close()
            return
        
        char_id, char_name, rarity_num = char
        rarity = get_rarity_by_num(rarity_num)
        
        # Marry the character
        c.execute("UPDATE user_chars SET married_to = ? WHERE char_id = ? AND user_id = ?", 
                 (user_id, char_id, user_id))
        c.execute("UPDATE users SET last_marry = ? WHERE user_id = ?", 
                 (datetime.now().isoformat(), user_id))
        
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"💞 **Marriage Success!**\n"
            f"────────────────\n"
            f"**{username}** married **{char_name}** {rarity['emoji']} [ID: {char_id}]!\n"
            f"────────────────\n"
            f"May your love last forever! 💍"
        )
        
        logger.info(f"User {user_id} married character {char_id}")
        
    except Exception as e:
        logger.error(f"Error in marry command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 16. /slot
@app.on_message(filters.command("slot"))
@group_only
async def slot_command(client, message):
    try:
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Check cooldown
        c.execute("SELECT last_slot FROM users WHERE user_id = ?", (user_id,))
        result = c.fetchone()
        
        if result and result[0]:
            remaining = get_cooldown_time(result[0], COOLDOWNS["slot"])
            if remaining > 0:
                await message.reply_text(
                    f"❌ **Slot machine on cooldown!**\n"
                    f"⏰ **Wait:** `{format_cooldown(remaining)}`\n"
                    f"Come back later!"
                )
                conn.close()
                return
        
        # Slot symbols
        symbols = ['🍎', '🍊', '🍇', '🍒', '🎃', '🔮']
        
        # Spin
        result = [random.choice(symbols) for _ in range(3)]
        
        # Check win
        win_amount = 0
        crystal_win = 0
        jackpot = 0
        message_text = ""
        
        if result[0] == result[1] == result[2]:
            win_amount = random.randint(10, 50)
            if result[0] == '🔮':
                crystal_win = random.randint(1, 10)
                jackpot = 1
                message_text = "🎉 **JACKPOT!** 🎉"
            else:
                message_text = "🎉 **Triple Match!** 🎉"
        elif result[0] == result[1] or result[1] == result[2] or result[0] == result[2]:
            win_amount = random.randint(5, 25)
            message_text = "✨ **Good match!** ✨"
        else:
            message_text = "😢 **Better luck next time!**"
        
        # Update balance
        if win_amount > 0:
            c.execute("UPDATE users SET thunder_coins = thunder_coins + ? WHERE user_id = ?", 
                     (win_amount, user_id))
            if crystal_win > 0:
                c.execute("UPDATE users SET lightning_crystals = lightning_crystals + ? WHERE user_id = ?", 
                         (crystal_win, user_id))
        
        # Update last slot time
        c.execute("UPDATE users SET last_slot = ? WHERE user_id = ?", 
                 (datetime.now().isoformat(), user_id))
        
        # Save history
        c.execute("""INSERT INTO slots_history (user_id, result, win_amount, jackpot, timestamp)
                     VALUES (?, ?, ?, ?, ?)""",
                  (user_id, ' '.join(result), win_amount, jackpot, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        
        # Create response
        response = (
            f"🎰 **SLOT MACHINE** 🎰\n"
            f"────────────────\n"
            f"`  {result[0]}  |  {result[1]}  |  {result[2]}  `\n"
            f"────────────────\n"
        )
        
        if win_amount > 0:
            response += f"{message_text}\n"
            response += f"**You won:** `{win_amount} ⚡`\n"
            if crystal_win > 0:
                response += f"**Jackpot bonus:** `{crystal_win} 🔮`\n"
        else:
            response += f"{message_text}\n"
        
        response += f"────────────────"
        
        await message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Error in slot command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 17. /redeem
@app.on_message(filters.command("redeem"))
@group_only
async def redeem_command(client, message):
    try:
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/redeem <code>`\nExample: `/redeem aB3xK9pL2`")
            return
        
        code = message.command[1]
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Check if code exists and is valid
        c.execute("""SELECT code_id, code_type, char_id, amount, uses, used_count 
                     FROM redeem_codes WHERE code = ? AND used_count < uses""", (code,))
        code_data = c.fetchone()
        
        if not code_data:
            await message.reply_text("❌ Invalid or expired code!")
            conn.close()
            return
        
        code_id, code_type, char_id, amount, uses, used_count = code_data
        
        if code_type == "character":
            # Get character details
            c.execute("SELECT name, anime, rarity_num, media_id FROM characters WHERE char_id = ?", (char_id,))
            char = c.fetchone()
            if not char:
                await message.reply_text("❌ Character not found!")
                conn.close()
                return
            
            name, anime, rarity_num, media_id = char
            rarity = get_rarity_by_num(rarity_num)
            
            # Add character to user
            c.execute("""INSERT INTO user_chars (user_id, char_id, acquired_date) 
                         VALUES (?, ?, ?)""", 
                      (user_id, char_id, datetime.now().isoformat()))
            c.execute("UPDATE users SET total_chars = total_chars + 1 WHERE user_id = ?", (user_id,))
            
            # Update code usage
            c.execute("UPDATE redeem_codes SET used_count = used_count + 1 WHERE code_id = ?", (code_id,))
            
            conn.commit()
            conn.close()
            
            # Send success message with image
            success_text = (
                f"🎉 **Redeemed Successfully!**\n"
                f"────────────────\n"
                f"🆎 **Type:** Character code\n"
                f"🪪 **Name:** {name}\n"
                f"🆔 **ID:** {char_id}\n"
                f"🃏 **Rarity:** {rarity['name']} {rarity['emoji']}\n"
                f"────────────────\n"
                f"Character added to your harem! Use `/harem` to view."
            )
            
            if media_id:
                await message.reply_photo(photo=media_id, caption=success_text)
            else:
                await message.reply_text(success_text)
            
            logger.info(f"User {user_id} redeemed character code for {name}")
        
        elif code_type == "thunder":
            # Add thunder coins to user
            c.execute("UPDATE users SET thunder_coins = thunder_coins + ? WHERE user_id = ?", 
                     (amount, user_id))
            
            # Update code usage
            c.execute("UPDATE redeem_codes SET used_count = used_count + 1 WHERE code_id = ?", (code_id,))
            
            conn.commit()
            conn.close()
            
            # Send success message
            success_text = (
                f"🎉 **Redeemed Successfully!**\n"
                f"────────────────\n"
                f"🆎 **Type:** Thunder coins ⚡\n"
                f"💵 **Amount:** {amount:,}\n"
                f"────────────────\n"
                f"Amount added to your balance! Use `/balance` to view."
            )
            
            await message.reply_text(success_text)
            logger.info(f"User {user_id} redeemed thunder code for {amount} ⚡")
        
    except Exception as e:
        logger.error(f"Error in redeem command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 18. /grab
@app.on_message(filters.command("grab") & filters.chat(SUPPORT_GROUP))
async def grab_command(client, message):
    try:
        if not message.reply_to_message:
            await message.reply_text("❌ Reply to a dropped character with `/grab`!")
            return
        
        user_id = message.from_user.id
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Check if it's a drop
        c.execute("""SELECT drop_id, char_id, status FROM char_drops 
                     WHERE message_id = ? AND chat_id = ?""",
                  (message.reply_to_message.id, SUPPORT_GROUP))
        drop = c.fetchone()
        
        if not drop:
            await message.reply_text("❌ Not a character drop!")
            conn.close()
            return
        
        drop_id, char_id, status = drop
        
        if status != 'active':
            await message.reply_text("❌ Character already grabbed!")
            conn.close()
            return
        
        # Get character details
        c.execute("SELECT name, anime, rarity_num FROM characters WHERE char_id = ?", (char_id,))
        char = c.fetchone()
        
        if not char:
            await message.reply_text("❌ Character not found!")
            conn.close()
            return
        
        name, anime, rarity_num = char
        rarity = get_rarity_by_num(rarity_num)
        
        # Give character to user
        c.execute("""INSERT INTO user_chars (user_id, char_id, acquired_date)
                     VALUES (?, ?, ?)""", (user_id, char_id, datetime.now().isoformat()))
        
        # Update drop status
        c.execute("UPDATE char_drops SET status = 'grabbed', grabbed_by = ? WHERE drop_id = ?",
                  (user_id, drop_id))
        
        # Update user total chars
        c.execute("UPDATE users SET total_chars = total_chars + 1 WHERE user_id = ?", (user_id,))
        
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"🎉 **Grabbed Successfully!**\n"
            f"────────────────\n"
            f"🪪 **Name:** {name}\n"
            f"🈲 **Anime:** {anime}\n"
            f"🆔 **ID:** {char_id}\n"
            f"🚨 **Rarity:** {rarity['name']} {rarity['emoji']}\n"
            f"────────────────\n"
            f"Use `/harem` to view the grabbed character!"
        )
        
        logger.info(f"User {user_id} grabbed character {name} (ID: {char_id})")
        
    except Exception as e:
        logger.error(f"Error in grab command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 19. /auctionlist
@app.on_message(filters.command("auctionlist"))
@group_only
async def auctionlist_command(client, message):
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Get active auctions
        c.execute("""SELECT auction_id, char_name, char_rarity, seller_name, current_bid, end_time 
                     FROM active_auctions WHERE status = 'active' 
                     ORDER BY end_time ASC""")
        active = c.fetchall()
        
        # Get completed auctions (last 10)
        c.execute("""SELECT char_name, char_rarity, seller_name, winner_name, final_bid, end_time
                     FROM auction_history WHERE winner_id IS NOT NULL
                     ORDER BY end_time DESC LIMIT 10""")
        completed = c.fetchall()
        
        conn.close()
        
        text = "📊 **AUCTION HOUSE** 📊\n\n"
        
        if active:
            text += "**🟢 ACTIVE AUCTIONS:**\n"
            for a in active[:5]:  # Show only 5 active
                auction_id, name, rarity, seller, bid, end = a
                end_time = datetime.fromisoformat(end)
                remaining = end_time - datetime.now()
                hours = remaining.seconds // 3600
                minutes = (remaining.seconds % 3600) // 60
                
                text += (
                    f"📌 **#{auction_id}:** {name} {rarity}\n"
                    f"   👤 Seller: {seller}\n"
                    f"   💰 Current: {bid:,} 🔮\n"
                    f"   ⏰ Ends in: {hours}h {minutes}m\n\n"
                )
        else:
            text += "🟢 No active auctions\n\n"
        
        if completed:
            text += "**📜 RECENT COMPLETED:**\n"
            for c in completed:
                name, rarity, seller, winner, bid, end = c
                date = datetime.fromisoformat(end).strftime("%m/%d")
                text += f"• {name} {rarity}\n"
                text += f"  💰 {bid:,} 🔮 | {seller} → {winner} | {date}\n\n"
        else:
            text += "📜 No completed auctions yet"
        
        await message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error in auctionlist command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 20. /bid
@app.on_message(filters.command("bid"))
@group_only
async def bid_command(client, message):
    try:
        if len(message.command) < 3:
            await message.reply_text("❌ **Usage:** `/bid <auction_id> <amount>`\nExample: `/bid 12345 5000`")
            return
        
        try:
            auction_id = int(message.command[1])
            bid_amount = int(message.command[2].replace(",", ""))
        except ValueError:
            await message.reply_text("❌ Invalid auction ID or bid amount!")
            return
        
        user_id = message.from_user.id
        username = message.from_user.first_name
        
        if bid_amount < 1:
            await message.reply_text("❌ Bid must be at least 1 🔮!")
            return
        
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        # Get auction
        c.execute("""SELECT char_name, char_rarity, seller_id, current_bid, 
                          current_bidder_id, end_time
                     FROM active_auctions WHERE auction_id = ? AND status = 'active'""", 
                  (auction_id,))
        auction = c.fetchone()
        
        if not auction:
            await message.reply_text("❌ Auction not found or ended!")
            conn.close()
            return
        
        char_name, char_rarity, seller_id, current_bid, current_bidder_id, end_time = auction
        
        # Check if ended
        if datetime.fromisoformat(end_time) < datetime.now():
            await process_auction_end(auction_id)
            await message.reply_text("❌ This auction has ended!")
            conn.close()
            return
        
        # Check if self-bidding
        if user_id == seller_id:
            await message.reply_text("❌ You cannot bid on your own auction!")
            conn.close()
            return
        
        # Check bid amount (minimum increment 5%)
        min_increment = max(int(current_bid * 0.05), 100)
        min_bid = current_bid + min_increment
        
        if bid_amount < min_bid:
            await message.reply_text(f"❌ Minimum bid is {min_bid:,} 🔮 (5% increment)!")
            conn.close()
            return
        
        # Check user's lightning crystals
        c.execute("SELECT lightning_crystals FROM users WHERE user_id = ?", (user_id,))
        balance = c.fetchone()
        
        if not balance or balance[0] < bid_amount:
            await message.reply_text(f"❌ You need {bid_amount:,} 🔮! You have: {balance[0] if balance else 0:,} 🔮")
            conn.close()
            return
        
        # Refund previous bidder
        if current_bidder_id:
            c.execute("UPDATE users SET lightning_crystals = lightning_crystals + ? WHERE user_id = ?",
                      (current_bid, current_bidder_id))
        
        # Deduct new bid
        c.execute("UPDATE users SET lightning_crystals = lightning_crystals - ? WHERE user_id = ?",
                  (bid_amount, user_id))
        
        # Update auction
        c.execute("""UPDATE active_auctions 
                     SET current_bid = ?, current_bidder_id = ?, current_bidder_name = ?
                     WHERE auction_id = ?""",
                  (bid_amount, user_id, username, auction_id))
        
        conn.commit()
        conn.close()
        
        await message.reply_text(
            f"✅ **Bid Placed!**\n"
            f"────────────────\n"
            f"📌 **Auction:** #{auction_id}\n"
            f"🎴 **Character:** {char_name} {char_rarity}\n"
            f"💰 **Your Bid:** {bid_amount:,} 🔮\n"
            f"────────────────\n"
            f"Good luck! 🍀"
        )
        
        logger.info(f"User {user_id} placed bid of {bid_amount} 🔮 on auction {auction_id}")
        
    except Exception as e:
        logger.error(f"Error in bid command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 21. /addcharpool (Uploader/Owner/Sudo only - DM)
@app.on_message(filters.command("addcharpool") & filters.private)
async def addcharpool_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check permission
        if not (is_uploader(user_id) or is_owner(user_id)):
            await message.reply_text("❌ You don't have permission to use this command!")
            return
        
        # Check if replying to media
        if not message.reply_to_message or not (message.reply_to_message.photo or message.reply_to_message.video):
            await message.reply_text(
                "❌ **Usage:** Reply to a photo/video with:\n"
                "`/addcharpool name|anime|rarity`\n\n"
                "**Example:**\n"
                "`/addcharpool Gojo Satoru|Jujutsu Kaisen|5`"
            )
            return
        
        if len(message.command) < 2:
            await message.reply_text("❌ Please provide character details!")
            return
        
        try:
            args = ' '.join(message.command[1:]).split('|')
            if len(args) != 3:
                await message.reply_text("❌ Format: `name|anime|rarity`")
                return
            
            name = args[0].strip()
            anime = args[1].strip()
            rarity_num = int(args[2].strip())
            
            if rarity_num not in RARITIES:
                await message.reply_text("❌ Invalid rarity! Use 1-11")
                return
            
            # Download media
            media = await download_media(message.reply_to_message)
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            # Save character
            c.execute("""INSERT INTO characters (name, anime, rarity_num, added_by, added_date)
                         VALUES (?, ?, ?, ?, ?)""",
                      (name, anime, rarity_num, user_id, datetime.now().isoformat()))
            
            char_id = c.lastrowid
            
            # Upload media and get file_id
            if message.reply_to_message.photo:
                sent_msg = await app.send_photo("me", photo=media)
                file_id = sent_msg.photo.file_id
            else:
                sent_msg = await app.send_video("me", video=media)
                file_id = sent_msg.video.file_id
            
            c.execute("UPDATE characters SET media_id = ? WHERE char_id = ?", (file_id, char_id))
            
            conn.commit()
            conn.close()
            
            await message.reply_text(
                f"✅ **Character Added Successfully!**\n"
                f"────────────────\n"
                f"**ID:** `{char_id}`\n"
                f"**Name:** {name}\n"
                f"**Anime:** {anime}\n"
                f"**Rarity:** {RARITIES[rarity_num]['name']} {RARITIES[rarity_num]['emoji']}\n"
                f"────────────────"
            )
            
            logger.info(f"User {user_id} added character {name} (ID: {char_id})")
            
        except ValueError:
            await message.reply_text("❌ Invalid rarity number! Use 1-11")
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in addcharpool command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 22. /gencharcode (Sudo/Owner only - DM)
@app.on_message(filters.command("gencharcode") & filters.private)
async def gencharcode_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check permission
        if not (is_sudo(user_id) or is_owner(user_id)):
            await message.reply_text("❌ Only sudo users can use this command!")
            return
        
        if len(message.command) < 3:
            await message.reply_text(
                "❌ **Usage:** `/gencharcode <char_id> <uses>`\n"
                "**Example:** `/gencharcode 8 10`"
            )
            return
        
        try:
            char_id = int(message.command[1])
            uses = int(message.command[2])
            
            if uses < 1 or uses > 100:
                await message.reply_text("❌ Uses must be between 1 and 100!")
                return
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            # Check if character exists
            c.execute("SELECT name FROM characters WHERE char_id = ?", (char_id,))
            char = c.fetchone()
            
            if not char:
                await message.reply_text("❌ Character not found!")
                conn.close()
                return
            
            char_name = char[0]
            
            # Generate unique code
            while True:
                code = generate_redeem_code("character", 8)
                c.execute("SELECT code_id FROM redeem_codes WHERE code = ?", (code,))
                if not c.fetchone():
                    break
            
            # Save code to database
            c.execute("""INSERT INTO redeem_codes 
                         (code, code_type, char_id, uses, created_by, created_date)
                         VALUES (?, 'character', ?, ?, ?, ?)""",
                      (code, char_id, uses, user_id, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            
            # Send formatted message
            response = (
                f"🌌 **Redeem Code Created!**\n"
                f"────────────────\n"
                f"👩‍💻 **Code:** `{code}`\n"
                f"🎴 **Type:** Character code\n"
                f"🪪 **Character ID:** `{char_id}`\n"
                f"📝 **Character:** {char_name}\n"
                f"🔟 **Uses:** {uses}\n"
                f"────────────────\n"
                f"Redeem using `/redeem {code}`"
            )
            
            await message.reply_text(response)
            logger.info(f"User {user_id} generated character code for ID {char_id}")
            
        except ValueError:
            await message.reply_text("❌ Invalid character ID or uses!")
            
    except Exception as e:
        logger.error(f"Error in gencharcode command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 23. /genthundercode (Sudo/Owner only - DM)
@app.on_message(filters.command("genthundercode") & filters.private)
async def genthundercode_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check permission
        if not (is_sudo(user_id) or is_owner(user_id)):
            await message.reply_text("❌ Only sudo users can use this command!")
            return
        
        if len(message.command) < 3:
            await message.reply_text(
                "❌ **Usage:** `/genthundercode <amount> <uses>`\n"
                "**Example:** `/genthundercode 10000 3`"
            )
            return
        
        try:
            amount = int(message.command[1])
            uses = int(message.command[2])
            
            if amount < 100 or amount > 100000000:
                await message.reply_text("❌ Amount must be between 100 and 100,000,000 ⚡!")
                return
            
            if uses < 1 or uses > 100:
                await message.reply_text("❌ Uses must be between 1 and 100!")
                return
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            # Generate unique code
            while True:
                code = generate_redeem_code("thunder", 12)
                c.execute("SELECT code_id FROM redeem_codes WHERE code = ?", (code,))
                if not c.fetchone():
                    break
            
            # Save code to database
            c.execute("""INSERT INTO redeem_codes 
                         (code, code_type, amount, uses, created_by, created_date)
                         VALUES (?, 'thunder', ?, ?, ?, ?)""",
                      (code, amount, uses, user_id, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            
            # Send formatted message
            response = (
                f"🌌 **Redeem Code Generated!**\n"
                f"────────────────\n"
                f"👩‍💻 **Code:** `{code}`\n"
                f"🆎 **Type:** Thunder coins ⚡\n"
                f"💵 **Amount:** {amount:,}\n"
                f"🔟 **Uses:** {uses}\n"
                f"────────────────\n"
                f"Redeem using `/redeem {code}`"
            )
            
            await message.reply_text(response)
            logger.info(f"User {user_id} generated thunder code for {amount} ⚡")
            
        except ValueError:
            await message.reply_text("❌ Invalid amount or uses!")
            
    except Exception as e:
        logger.error(f"Error in genthundercode command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 24. /addauctionmaker (Owner only)
@app.on_message(filters.command("addauctionmaker") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addauctionmaker_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/addauctionmaker <user_id>`\nExample: `/addauctionmaker 123456789`")
            return
        
        try:
            target_id = int(message.command[1])
            user = await client.get_users(target_id)
            username = user.first_name
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("""INSERT OR REPLACE INTO auction_makers 
                         (user_id, username, added_by, added_date)
                         VALUES (?, ?, ?, ?)""",
                      (target_id, username, user_id, datetime.now().isoformat()))
            
            conn.commit()
            conn.close()
            
            await message.reply_text(
                f"✅ **Auction Maker Added!**\n"
                f"────────────────\n"
                f"**User:** {username}\n"
                f"**ID:** `{target_id}`\n"
                f"────────────────\n"
                f"They can now create auctions using `/auctioncreate`"
            )
            
            logger.info(f"Owner {user_id} added auction maker {target_id}")
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID!")
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in addauctionmaker command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 25. /removeauctioner (Owner only)
@app.on_message(filters.command("removeauctioner") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def removeauctioner_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/removeauctioner <user_id>`\nExample: `/removeauctioner 123456789`")
            return
        
        try:
            target_id = int(message.command[1])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("DELETE FROM auction_makers WHERE user_id = ?", (target_id,))
            deleted = c.rowcount
            
            conn.commit()
            conn.close()
            
            if deleted > 0:
                await message.reply_text(f"✅ Removed auction maker: `{target_id}`")
                logger.info(f"Owner {user_id} removed auction maker {target_id}")
            else:
                await message.reply_text(f"❌ User `{target_id}` is not an auction maker!")
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID!")
            
    except Exception as e:
        logger.error(f"Error in removeauctioner command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 26. /auctioncreate (Auction Maker only - with image)
@app.on_message(filters.command("auctioncreate"))
@group_only
async def auctioncreate_command(client, message):
    try:
        user_id = message.from_user.id
        username = message.from_user.first_name
        
        # Check if auction maker or owner
        if not (is_auction_maker(user_id) or is_owner(user_id)):
            await message.reply_text("❌ Only auction makers can create auctions!")
            return
        
        if len(message.command) < 2:
            await message.reply_text(
                "❌ **Usage:** `/auctioncreate <char_info> || <duration> || <starting_bid>`\n"
                "**Example:** `/auctioncreate gojosaturo (8) 🎃|| 1 day || 10000`"
            )
            return
        
        try:
            full_text = ' '.join(message.command[1:])
            parts = full_text.split("||")
            
            if len(parts) != 3:
                await message.reply_text("❌ Format: `<char_info> || <duration> || <starting_bid>`")
                return
            
            char_info = parts[0].strip()
            duration_text = parts[1].strip().lower()
            starting_bid = parts[2].strip().replace(",", "")
            
            # Validate starting bid (1 to 100 million 🔮)
            try:
                starting_bid = int(starting_bid)
                if starting_bid < 1 or starting_bid > 100000000:
                    await message.reply_text("❌ Starting bid must be between 1 and 100,000,000 🔮!")
                    return
            except ValueError:
                await message.reply_text("❌ Invalid starting bid!")
                return
            
            # Parse duration (max 36 hours)
            duration_hours = 0
            if "day" in duration_text:
                days = 1
                if duration_text.split("day")[0].strip().isdigit():
                    days = int(duration_text.split("day")[0].strip())
                duration_hours += days * 24
                
                if "hour" in duration_text:
                    hours_part = duration_text.split("hour")[0].split()[-1]
                    if hours_part.isdigit():
                        duration_hours += int(hours_part)
            elif "hour" in duration_text:
                hours = int(''.join(filter(str.isdigit, duration_text)))
                duration_hours = hours
            
            if duration_hours > 36:
                await message.reply_text("❌ Max duration is 1 day 12 hours (36 hours)!")
                return
            if duration_hours < 1:
                await message.reply_text("❌ Min duration is 1 hour!")
                return
            
            # Extract char_id from format "name (id) emoji"
            char_id_match = re.search(r'\((\d+)\)', char_info)
            if not char_id_match:
                await message.reply_text("❌ Character ID not found! Use format: `name (id) emoji`")
                return
            
            char_id = int(char_id_match.group(1))
            
            # Get character details
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("SELECT name, rarity_num, media_id FROM characters WHERE char_id = ?", (char_id,))
            char = c.fetchone()
            
            if not char:
                await message.reply_text("❌ Character not found!")
                conn.close()
                return
            
            char_name, rarity_num, media_id = char
            rarity = get_rarity_by_num(rarity_num)
            char_rarity = f"{rarity['name']} {rarity['emoji']}"
            
            # Check if user owns this character
            if not check_user_has_char(user_id, char_id):
                await message.reply_text("❌ You don't own this character!")
                conn.close()
                return
            
            # Calculate end time
            end_time = datetime.now() + timedelta(hours=duration_hours)
            
            # Generate auction ID
            auction_id = random.randint(10000, 99999)
            
            # Create auction
            c.execute("""INSERT INTO active_auctions 
                         (auction_id, char_name, char_rarity, char_id, seller_id, 
                          seller_name, current_bid, end_time, min_bid)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                      (auction_id, char_name, char_rarity, char_id, user_id, 
                       username, starting_bid, end_time.isoformat(), starting_bid))
            
            # Remove character from user's inventory
            c.execute("DELETE FROM user_chars WHERE user_id = ? AND char_id = ?", (user_id, char_id))
            c.execute("UPDATE users SET total_chars = total_chars - 1 WHERE user_id = ?", (user_id,))
            
            conn.commit()
            conn.close()
            
            # Format duration display
            if duration_hours >= 24:
                days = duration_hours // 24
                hours = duration_hours % 24
                duration_display = f"{days}d {hours}h" if hours > 0 else f"{days}d"
            else:
                duration_display = f"{duration_hours}h"
            
            # Auction created message with image
            caption = (
                f"✅ **Auction Created Successfully!**\n"
                f"────────────────\n"
                f"📌 **Auction ID:** `{auction_id}`\n"
                f"🎴 **Character:** {char_name} {rarity['emoji']}\n"
                f"🆔 **Character ID:** `{char_id}`\n"
                f"📊 **Rarity:** {rarity['name']} {rarity['emoji']}\n"
                f"💰 **Starting Bid:** {starting_bid:,} 🔮\n"
                f"⏰ **Duration:** {duration_display}\n"
                f"⏱ **Ends At:** {end_time.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                f"────────────────\n"
                f"📢 **Auction Rules:**\n"
                f"• Minimum bid increment: 5%\n"
                f"• Bids must be in Lightning Crystals 🔮\n"
                f"• Cannot bid on your own auction\n\n"
                f"🎯 **Place a bid:** `/bid {auction_id} <amount>`\n"
                f"📊 **View auctions:** `/auctionlist`"
            )
            
            if media_id:
                await message.reply_photo(photo=media_id, caption=caption)
            else:
                await message.reply_text(caption)
            
            logger.info(f"User {user_id} created auction #{auction_id} for character {char_id}")
            
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")
            
    except Exception as e:
        logger.error(f"Error in auctioncreate command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 27. /addthundercoins (Owner only)
@app.on_message(filters.command("addthundercoins") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addthundercoins_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 3:
            await message.reply_text("❌ **Usage:** `/addthundercoins <user_id> <amount>`\nExample: `/addthundercoins 123456789 50000`")
            return
        
        try:
            target_id = int(message.command[1])
            amount = int(message.command[2])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("UPDATE users SET thunder_coins = thunder_coins + ? WHERE user_id = ?", 
                     (amount, target_id))
            
            if c.rowcount == 0:
                await message.reply_text("❌ User not found!")
            else:
                await message.reply_text(
                    f"✅ **Added Thunder Coins!**\n"
                    f"────────────────\n"
                    f"**User:** `{target_id}`\n"
                    f"**Amount:** `{amount:,} ⚡`\n"
                    f"────────────────"
                )
                logger.info(f"Owner {user_id} added {amount} ⚡ to user {target_id}")
            
            conn.commit()
            conn.close()
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID or amount!")
            
    except Exception as e:
        logger.error(f"Error in addthundercoins command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 28. /addlightningcrystal (Owner only)
@app.on_message(filters.command("addlightningcrystal") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addlightningcrystal_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 3:
            await message.reply_text("❌ **Usage:** `/addlightningcrystal <user_id> <amount>`\nExample: `/addlightningcrystal 123456789 100`")
            return
        
        try:
            target_id = int(message.command[1])
            amount = int(message.command[2])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("UPDATE users SET lightning_crystals = lightning_crystals + ? WHERE user_id = ?", 
                     (amount, target_id))
            
            if c.rowcount == 0:
                await message.reply_text("❌ User not found!")
            else:
                await message.reply_text(
                    f"✅ **Added Lightning Crystals!**\n"
                    f"────────────────\n"
                    f"**User:** `{target_id}`\n"
                    f"**Amount:** `{amount:,} 🔮`\n"
                    f"────────────────"
                )
                logger.info(f"Owner {user_id} added {amount} 🔮 to user {target_id}")
            
            conn.commit()
            conn.close()
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID or amount!")
            
    except Exception as e:
        logger.error(f"Error in addlightningcrystal command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 29. /adduploader (Owner only)
@app.on_message(filters.command("adduploader") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def adduploader_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/adduploader <user_id>`\nExample: `/adduploader 123456789`")
            return
        
        try:
            target_id = int(message.command[1])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            # Check if user exists
            c.execute("SELECT username FROM users WHERE user_id = ?", (target_id,))
            user = c.fetchone()
            
            if not user:
                # Try to get from Telegram
                try:
                    target = await client.get_users(target_id)
                    username = target.first_name
                    c.execute("INSERT INTO users (user_id, username, role) VALUES (?, ?, 'uploader')", 
                             (target_id, username))
                except:
                    await message.reply_text("❌ User not found!")
                    conn.close()
                    return
            else:
                c.execute("UPDATE users SET role = 'uploader' WHERE user_id = ?", (target_id,))
            
            conn.commit()
            conn.close()
            
            await message.reply_text(
                f"✅ **Uploader Added!**\n"
                f"────────────────\n"
                f"**User:** `{target_id}`\n"
                f"────────────────\n"
                f"They can now use `/addcharpool` in DM"
            )
            
            logger.info(f"Owner {user_id} made {target_id} an uploader")
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID!")
            
    except Exception as e:
        logger.error(f"Error in adduploader command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 30. /removeuploader (Owner only)
@app.on_message(filters.command("removeuploader") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def removeuploader_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/removeuploader <user_id>`\nExample: `/removeuploader 123456789`")
            return
        
        try:
            target_id = int(message.command[1])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("UPDATE users SET role = 'user' WHERE user_id = ? AND role = 'uploader'", (target_id,))
            updated = c.rowcount
            
            conn.commit()
            conn.close()
            
            if updated > 0:
                await message.reply_text(f"✅ Removed uploader from `{target_id}`")
                logger.info(f"Owner {user_id} removed uploader from {target_id}")
            else:
                await message.reply_text(f"❌ User `{target_id}` is not an uploader!")
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID!")
            
    except Exception as e:
        logger.error(f"Error in removeuploader command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 31. /addsudo (Owner only)
@app.on_message(filters.command("addsudo") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addsudo_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/addsudo <user_id>`\nExample: `/addsudo 123456789`")
            return
        
        try:
            target_id = int(message.command[1])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            # Check if user exists
            c.execute("SELECT username FROM users WHERE user_id = ?", (target_id,))
            user = c.fetchone()
            
            if not user:
                # Try to get from Telegram
                try:
                    target = await client.get_users(target_id)
                    username = target.first_name
                    c.execute("INSERT INTO users (user_id, username, role) VALUES (?, ?, 'sudo')", 
                             (target_id, username))
                except:
                    await message.reply_text("❌ User not found!")
                    conn.close()
                    return
            else:
                c.execute("UPDATE users SET role = 'sudo' WHERE user_id = ?", (target_id,))
            
            conn.commit()
            conn.close()
            
            await message.reply_text(
                f"✅ **Sudo User Added!**\n"
                f"────────────────\n"
                f"**User:** `{target_id}`\n"
                f"────────────────\n"
                f"They can now use sudo commands in DM"
            )
            
            logger.info(f"Owner {user_id} made {target_id} a sudo user")
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID!")
            
    except Exception as e:
        logger.error(f"Error in addsudo command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 32. /removesudo (Owner only)
@app.on_message(filters.command("removesudo") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def removesudo_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 2:
            await message.reply_text("❌ **Usage:** `/removesudo <user_id>`\nExample: `/removesudo 123456789`")
            return
        
        try:
            target_id = int(message.command[1])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            c.execute("UPDATE users SET role = 'user' WHERE user_id = ? AND role = 'sudo'", (target_id,))
            updated = c.rowcount
            
            conn.commit()
            conn.close()
            
            if updated > 0:
                await message.reply_text(f"✅ Removed sudo from `{target_id}`")
                logger.info(f"Owner {user_id} removed sudo from {target_id}")
            else:
                await message.reply_text(f"❌ User `{target_id}` is not a sudo user!")
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID!")
            
    except Exception as e:
        logger.error(f"Error in removesudo command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 33. /addcharid (Owner only)
@app.on_message(filters.command("addcharid") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addcharid_command(client, message):
    try:
        user_id = message.from_user.id
        
        # Check if owner
        if not is_owner(user_id):
            await message.reply_text("❌ Only owner can use this command!")
            return
        
        if len(message.command) < 3:
            await message.reply_text("❌ **Usage:** `/addcharid <user_id> <char_id>`\nExample: `/addcharid 123456789 8`")
            return
        
        try:
            target_id = int(message.command[1])
            char_id = int(message.command[2])
            
            conn = sqlite3.connect('character_bot.db')
            c = conn.cursor()
            
            # Check if character exists
            c.execute("SELECT name FROM characters WHERE char_id = ?", (char_id,))
            char = c.fetchone()
            
            if not char:
                await message.reply_text("❌ Character not found!")
                conn.close()
                return
            
            char_name = char[0]
            
            # Check if user exists
            c.execute("SELECT user_id FROM users WHERE user_id = ?", (target_id,))
            if not c.fetchone():
                # Try to get from Telegram
                try:
                    target = await client.get_users(target_id)
                    username = target.first_name
                    c.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", 
                             (target_id, username))
                except:
                    await message.reply_text("❌ User not found!")
                    conn.close()
                    return
            
            # Give character to user
            c.execute("""INSERT INTO user_chars (user_id, char_id, acquired_date)
                         VALUES (?, ?, ?)""",
                      (target_id, char_id, datetime.now().isoformat()))
            
            c.execute("UPDATE users SET total_chars = total_chars + 1 WHERE user_id = ?", (target_id,))
            
            conn.commit()
            conn.close()
            
            await message.reply_text(
                f"✅ **Character Given!**\n"
                f"────────────────\n"
                f"**User:** `{target_id}`\n"
                f"**Character:** {char_name} [ID: {char_id}]\n"
                f"────────────────"
            )
            
            logger.info(f"Owner {user_id} gave character {char_id} to user {target_id}")
            
        except ValueError:
            await message.reply_text("❌ Invalid user ID or character ID!")
            
    except Exception as e:
        logger.error(f"Error in addcharid command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 34. /staff
@app.on_message(filters.command("staff") & filters.chat(SUPPORT_GROUP))
async def staff_command(client, message):
    try:
        conn = sqlite3.connect('character_bot.db')
        c = conn.cursor()
        
        c.execute("""SELECT user_id, username, role FROM users 
                     WHERE role IN ('sudo', 'uploader', 'owner') 
                     ORDER BY role""")
        staff = c.fetchall()
        conn.close()
        
        if not staff:
            await message.reply_text("📢 No staff members yet!")
            return
        
        text = "👥 **Staff Members** 👥\n\n"
        for user_id, username, role in staff:
            emoji = "👑" if role == "owner" else "⚡" if role == "sudo" else "📤"
            text += f"{emoji} **{username}**\n"
            text += f"   🆔 `{user_id}`\n"
            text += f"   🎯 Role: {role}\n\n"
        
        await message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error in staff command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 35. /sudopanel (Sudo only - DM)
@app.on_message(filters.command("sudopanel") & filters.private)
async def sudopanel_command(client, message):
    try:
        user_id = message.from_user.id
        
        if not (is_sudo(user_id) or is_owner(user_id)):
            await message.reply_text("❌ Only sudo users can access this panel!")
            return
        
        text = (
            f"⚡ **SUDO PANEL** ⚡\n"
            f"────────────────\n"
            f"**Commands you can use:**\n\n"
            f"📤 `/addcharpool` - Add characters (reply to media)\n"
            f"🔑 `/gencharcode` - Generate character codes\n"
            f"💰 `/genthundercode` - Generate thunder coin codes\n"
            f"────────────────\n"
            f"📍 *Use these commands in DM*\n\n"
            f"👤 **Your Role:** {get_user_role(user_id)}"
        )
        
        await message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error in sudopanel command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 36. /uploaderpanel (Uploader only - DM)
@app.on_message(filters.command("uploaderpanel") & filters.private)
async def uploaderpanel_command(client, message):
    try:
        user_id = message.from_user.id
        
        if not (is_uploader(user_id) or is_owner(user_id)):
            await message.reply_text("❌ Only uploaders can access this panel!")
            return
        
        text = (
            f"📤 **UPLOADER PANEL** 📤\n"
            f"────────────────\n"
            f"**Commands you can use:**\n\n"
            f"📸 `/addcharpool` - Add characters (reply to media)\n"
            f"────────────────\n"
            f"📍 *Use this command in DM*\n\n"
            f"👤 **Your Role:** {get_user_role(user_id)}"
        )
        
        await message.reply_text(text)
        
    except Exception as e:
        logger.error(f"Error in uploaderpanel command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 37. /help
@app.on_message(filters.command("help"))
async def help_command(client, message):
    try:
        user_id = message.from_user.id
        role = get_user_role(user_id)
        
        help_text = "📚 **COMMANDS** 📚\n\n"
        help_text += "**👤 USER COMMANDS:**\n"
        help_text += "`/start` `/profile` `/balance` `/daily` `/weekly`\n"
        help_text += "`/claim` `/exchange` `/gift` `/harem` `/find`\n"
        help_text += "`/cfind` `/fav` `/unfav` `/top` `/marry`\n"
        help_text += "`/slot` `/redeem` `/grab` `/auctionlist` `/bid`\n\n"
        
        if is_auction_maker(user_id) or is_owner(user_id):
            help_text += "**🏷️ AUCTION MAKER COMMANDS:**\n"
            help_text += "`/auctioncreate`\n\n"
        
        if is_uploader(user_id):
            help_text += "**📤 UPLOADER COMMANDS:**\n"
            help_text += "`/addcharpool` (DM only)\n"
            help_text += "`/uploaderpanel` - View your commands\n\n"
        
        if is_sudo(user_id):
            help_text += "**⚡ SUDO COMMANDS:**\n"
            help_text += "`/gencharcode` `/genthundercode` (DM only)\n"
            help_text += "`/sudopanel` - View your commands\n\n"
        
        if is_owner(user_id):
            help_text += "**👑 OWNER COMMANDS:**\n"
            help_text += "`/addthundercoins` `/addlightningcrystal`\n"
            help_text += "`/adduploader` `/removeuploader`\n"
            help_text += "`/addsudo` `/removesudo` `/addcharid`\n"
            help_text += "`/addauctionmaker` `/removeauctioner`\n\n"
        
        help_text += "**📊 OTHER:**\n"
        help_text += "`/staff` `/help`"
        
        if not is_support_group(message.chat.id):
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Join Support Group", url=SUPPORT_GROUP_LINK)
            ]])
            await message.reply_text(
                "❌ Commands only work in support group!\n\n" + help_text, 
                reply_markup=keyboard
            )
        else:
            await message.reply_text(help_text)
            
    except Exception as e:
        logger.error(f"Error in help command: {e}")
        await message.reply_text("❌ An error occurred. Please try again.")

# 38. Callback handler (for pagination)
@app.on_callback_query()
async def handle_callbacks(client, callback_query: CallbackQuery):
    try:
        data = callback_query.data
        user_id = callback_query.from_user.id
        
        # Handle harem pagination
        if data.startswith("harem_"):
            page = int(data.split("_")[1])
            chars, total = get_user_chars_page(user_id, page)
            
            if not chars:
                await callback_query.answer("No characters found!")
                return
            
            total_pages = ((total - 1) // 10) + 1
            
            text = f"🎴 **Your Harem** (Page {page}/{total_pages}) 🎴\n\n"
            
            for i, char in enumerate(chars, 1):
                name, rarity_num, char_id, is_fav = char
                rarity = get_rarity_by_num(rarity_num)
                fav_star = "⭐ " if is_fav else ""
                text += f"{fav_star}{i}. **{name}** {rarity['emoji']} [ID: {char_id}]\n"
            
            buttons = []
            if page > 1:
                buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"harem_{page-1}"))
            if page < total_pages:
                buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"harem_{page+1}"))
            
            keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
            await callback_query.message.edit_text(text, reply_markup=keyboard)
            await callback_query.answer()
        
        # Handle find pagination
        elif data.startswith("find_"):
            parts = data.split("_")
            search_term = parts[1]
            page = int(parts[2])
            
            chars, total = find_chars_page(search_term, page)
            
            if not chars:
                await callback_query.answer("No results found!")
                return
            
            total_pages = ((total - 1) // 10) + 1
            
            text = f"🔍 **Results for:** '{search_term}' (Page {page}/{total_pages})\n"
            text += "─" * 30 + "\n"
            
            for i, char in enumerate(chars, 1):
                char_id, name, anime, rarity_num = char
                rarity = get_rarity_by_num(rarity_num)
                text += f"{i}. **{name}** {rarity['emoji']} [ID: {char_id}]\n"
            
            buttons = []
            if page > 1:
                buttons.append(InlineKeyboardButton("◀️ Prev", callback_data=f"find_{search_term}_{page-1}"))
            if page < total_pages:
                buttons.append(InlineKeyboardButton("Next ▶️", callback_data=f"find_{search_term}_{page+1}"))
            
            keyboard = InlineKeyboardMarkup([buttons]) if buttons else None
            await callback_query.message.edit_text(text, reply_markup=keyboard)
            await callback_query.answer()
        
        else:
            await callback_query.answer("Unknown callback!")
            
    except Exception as e:
        logger.error(f"Error in callback handler: {e}")
        await callback_query.answer("An error occurred!")

# ============================================
# COMMAND HANDLERS - 38 COMMANDS
# ============================================

# 1. /start
@app.on_message(filters.command("start"))
async def start_command(client, message):
    # Handler code
    pass

# 2. /profile
@app.on_message(filters.command("profile"))
@group_only
async def profile_command(client, message):
    # Handler code
    pass

# 3. /balance
@app.on_message(filters.command("balance"))
@group_only
async def balance_command(client, message):
    # Handler code
    pass

# 4. /daily
@app.on_message(filters.command("daily"))
@group_only
async def daily_command(client, message):
    # Handler code
    pass

# 5. /weekly
@app.on_message(filters.command("weekly"))
@group_only
async def weekly_command(client, message):
    # Handler code
    pass

# 6. /claim
@app.on_message(filters.command("claim"))
@group_only
async def claim_command(client, message):
    # Handler code
    pass

# 7. /exchange
@app.on_message(filters.command("exchange"))
@group_only
async def exchange_command(client, message):
    # Handler code
    pass

# 8. /gift
@app.on_message(filters.command("gift"))
@group_only
async def gift_command(client, message):
    # Handler code
    pass

# 9. /harem
@app.on_message(filters.command("harem"))
@group_only
async def harem_command(client, message):
    # Handler code
    pass

# 10. /find
@app.on_message(filters.command("find"))
@group_only
async def find_command(client, message):
    # Handler code
    pass

# 11. /cfind
@app.on_message(filters.command("cfind"))
@group_only
async def cfind_command(client, message):
    # Handler code
    pass

# 12. /fav
@app.on_message(filters.command("fav"))
@group_only
async def fav_command(client, message):
    # Handler code
    pass

# 13. /unfav
@app.on_message(filters.command("unfav"))
@group_only
async def unfav_command(client, message):
    # Handler code
    pass

# 14. /top
@app.on_message(filters.command("top"))
@group_only
async def top_command(client, message):
    # Handler code
    pass

# 15. /marry
@app.on_message(filters.command("marry"))
@group_only
async def marry_command(client, message):
    # Handler code
    pass

# 16. /slot
@app.on_message(filters.command("slot"))
@group_only
async def slot_command(client, message):
    # Handler code
    pass

# 17. /redeem
@app.on_message(filters.command("redeem"))
@group_only
async def redeem_command(client, message):
    # Handler code
    pass

# 18. /grab
@app.on_message(filters.command("grab") & filters.chat(SUPPORT_GROUP))
async def grab_command(client, message):
    # Handler code
    pass

# 19. /auctionlist
@app.on_message(filters.command("auctionlist"))
@group_only
async def auctionlist_command(client, message):
    # Handler code
    pass

# 20. /bid
@app.on_message(filters.command("bid"))
@group_only
async def bid_command(client, message):
    # Handler code
    pass

# 21. /addcharpool
@app.on_message(filters.command("addcharpool") & filters.private)
async def addcharpool_command(client, message):
    # Handler code
    pass

# 22. /gencharcode
@app.on_message(filters.command("gencharcode") & filters.private)
async def gencharcode_command(client, message):
    # Handler code
    pass

# 23. /genthundercode
@app.on_message(filters.command("genthundercode") & filters.private)
async def genthundercode_command(client, message):
    # Handler code
    pass

# 24. /addauctionmaker
@app.on_message(filters.command("addauctionmaker") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addauctionmaker_command(client, message):
    # Handler code
    pass

# 25. /removeauctioner
@app.on_message(filters.command("removeauctioner") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def removeauctioner_command(client, message):
    # Handler code
    pass

# 26. /auctioncreate
@app.on_message(filters.command("auctioncreate"))
@group_only
async def auctioncreate_command(client, message):
    # Handler code
    pass

# 27. /addthundercoins
@app.on_message(filters.command("addthundercoins") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addthundercoins_command(client, message):
    # Handler code
    pass

# 28. /addlightningcrystal
@app.on_message(filters.command("addlightningcrystal") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addlightningcrystal_command(client, message):
    # Handler code
    pass

# 29. /adduploader
@app.on_message(filters.command("adduploader") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def adduploader_command(client, message):
    # Handler code
    pass

# 30. /removeuploader
@app.on_message(filters.command("removeuploader") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def removeuploader_command(client, message):
    # Handler code
    pass

# 31. /addsudo
@app.on_message(filters.command("addsudo") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addsudo_command(client, message):
    # Handler code
    pass

# 32. /removesudo
@app.on_message(filters.command("removesudo") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def removesudo_command(client, message):
    # Handler code
    pass

# 33. /addcharid
@app.on_message(filters.command("addcharid") & (filters.private | filters.chat(SUPPORT_GROUP)))
async def addcharid_command(client, message):
    # Handler code
    pass

# 34. /staff
@app.on_message(filters.command("staff") & filters.chat(SUPPORT_GROUP))
async def staff_command(client, message):
    # Handler code
    pass

# 35. /sudopanel
@app.on_message(filters.command("sudopanel") & filters.private)
async def sudopanel_command(client, message):
    # Handler code
    pass

# 36. /uploaderpanel
@app.on_message(filters.command("uploaderpanel") & filters.private)
async def uploaderpanel_command(client, message):
    # Handler code
    pass

# 37. /help
@app.on_message(filters.command("help"))
async def help_command(client, message):
    # Handler code
    pass

# 38. Callback handler
@app.on_callback_query()
async def handle_callbacks(client, callback_query: CallbackQuery):
    # Handler code
    pass

# ============================================
# MAIN FUNCTION
# ============================================

async def main():
    print("🤖 BOT STARTING...")
    print(f"👤 Owner ID: {OWNER_ID}")
    print(f"💬 Support Group: {SUPPORT_GROUP}")
    print("✅ Bot is running!")
    print("bot started")
    
    await app.start()
    
    # Start background tasks
    asyncio.create_task(char_drop_system())
    asyncio.create_task(check_auction_ends())
    
    # Keep bot running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    try:
        app.run(main())
    except KeyboardInterrupt:
        print("👋 Bot stopped!")
        sys.exit(0)  