import os
import logging
from datetime import datetime
from io import BytesIO
import uuid

# Telegram Bot
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# Supabase
from supabase import create_client, Client

# Google Cloud Vision
from google.cloud import vision
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Environment variables
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

# Initialize clients
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
vision_client = vision.ImageAnnotatorClient()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NotesBot:
    def __init__(self):
        self.supabase = supabase
        self.vision_client = vision_client
        
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        welcome_message = (
            "🤖 Welcome to Screenshot Notes Bot!\n\n"
            "📸 Send me any screenshot and I'll:\n"
            "• Extract all text using OCR\n"
            "• Generate a title and tags\n"
            "• Save it to your notes database\n\n"
            "Just send me an image to get started!"
        )
        await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        help_message = (
            "📋 How to use this bot:\n\n"
            "1. Send any screenshot or image with text\n"
            "2. I'll analyze it and extract the text\n"
            "3. Your note will be saved with:\n"
            "   • Auto-generated title\n"
            "   • Relevant tags\n"
            "   • Full extracted text content\n\n"
            "Commands:\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n"
            "/stats - Show your notes statistics"
        )
        await update.message.reply_text(help_message)

    async def stats_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /stats command"""
        try:
            user_id = update.effective_user.id
            result = self.supabase.table('notes').select('id').eq('user_id', user_id).execute()
            notes_count = len(result.data) if result.data else 0
            
            stats_message = f"📊 Your Statistics:\n\n📝 Total Notes: {notes_count}"
            await update.message.reply_text(stats_message)
            
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            await update.message.reply_text("❌ Error retrieving statistics.")

    def extract_text_from_image(self, image_bytes: bytes) -> str:
        """Extract text from image using Google Cloud Vision API"""
        try:
            image = vision.Image(content=image_bytes)
            response = self.vision_client.text_detection(image=image)
            
            if response.text_annotations:
                return response.text_annotations[0].description
            return ""
            
        except Exception as e:
            logger.error(f"Error extracting text from image: {e}")
            return ""

    def generate_title_from_text(self, text: str) -> str:
        """Generate a smart short title from text content"""
        if not text:
            return "Скриншот"
        
        text_lower = text.lower()
        
        # Topic keywords for smart recognition
        topics = {
            'ACID': ['acid', 'атомарность', 'consistency', 'isolation'],
            'База данных': ['база данных', 'database', 'sql', 'таблица'],
            'Код': ['def ', 'function', 'import', 'class ', 'код'],
            'Настройки': ['настройки', 'settings', 'конфигурация'],
            'Ошибка': ['error', 'exception', 'ошибка', 'failed'],
            'Урок': ['урок', 'tutorial', 'гайд', 'обучение'],
            'Чат': ['чат', 'сообщение', 'message', 'диалог'],
            'Документ': ['документ', 'статья', 'document'],
            'Сайт': ['http', 'www', 'сайт', 'website'],
            'Деньги': ['рубль', 'деньги', 'цена', '$', '€', '₽']
        }
        
        # Check for topic matches
        for topic, keywords in topics.items():
            for keyword in keywords:
                if keyword in text_lower:
                    return topic
        
        # Extract from first line
        lines = text.split('\n')
        if lines:
            first_line = lines[0].strip()
            words = first_line.split()[:3]  # Take first 3 words
            if words:
                title = ' '.join(words)
                return title if len(title) <= 30 else words[0]
        
        return "Скриншот"

    def generate_tags_from_text(self, text: str) -> list:
        """Generate tags from extracted text"""
        if not text:
            return ['screenshot']
        
        tags = ['screenshot']
        text_lower = text.lower()
        
        # Keywords for tagging
        tag_keywords = {
            'code': ['def ', 'function', 'import', 'class ', 'код', 'программа'],
            'database': ['database', 'sql', 'база данных', 'таблица', 'acid'],
            'email': ['@', 'email', 'почта', 'письмо'],
            'web': ['http', 'www', 'сайт', 'website'],
            'document': ['документ', 'статья', 'document'],
            'chat': ['чат', 'сообщение', 'message', 'диалог'],
            'settings': ['настройки', 'settings', 'конфигурация'],
            'error': ['error', 'ошибка', 'exception', 'failed'],
            'tutorial': ['урок', 'tutorial', 'гайд', 'обучение'],
            'financial': ['рубль', 'деньги', 'цена', '$', '€', '₽'],
            'education': ['школа', 'университет', 'студент', 'учеба'],
            'business': ['работа', 'офис', 'проект', 'задача']
        }
        
        for tag, keywords in tag_keywords.items():
            for keyword in keywords:
                if keyword in text_lower:
                    tags.append(tag)
                    break
        
        return list(set(tags))

    async def upload_image_to_supabase(self, image_bytes: bytes, filename: str) -> str:
        """Upload image to Supabase Storage"""
        try:
            self.supabase.storage.from_('screenshots').upload(
                filename, 
                image_bytes,
                file_options={"content-type": "image/jpeg"}
            )
            return self.supabase.storage.from_('screenshots').get_public_url(filename)
            
        except Exception as e:
            logger.error(f"Error uploading image: {e}")
            return None

    async def save_note_to_database(self, user_id: int, title: str, tags: list, content: str, image_url: str) -> bool:
        """Save note to database"""
        try:
            note_data = {
                'user_id': user_id,
                'title': title,
                'tags': tags,
                'content': content,
                'image_url': image_url,
                'created_at': datetime.utcnow().isoformat()
            }
            
            result = self.supabase.table('notes').insert(note_data).execute()
            return bool(result.data)
            
        except Exception as e:
            logger.error(f"Error saving note: {e}")
            return False

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle photo messages"""
        processing_msg = None
        try:
            # Send processing message
            processing_msg = await update.message.reply_text("🔍 Analyzing your screenshot...")
            
            # Get photo
            photo = update.message.photo[-1]
            file = await context.bot.get_file(photo.file_id)
            
            # Download image
            image_bytes = BytesIO()
            await file.download_to_memory(image_bytes)
            image_data = image_bytes.getvalue()
            
            # Extract text
            extracted_text = self.extract_text_from_image(image_data)
            
            if not extracted_text:
                await processing_msg.edit_text("❌ No text found in the image.")
                return
            
            # Generate title and tags
            title = self.generate_title_from_text(extracted_text)
            tags = self.generate_tags_from_text(extracted_text)
            
            # Upload image
            filename = f"screenshot_{uuid.uuid4()}_{int(datetime.now().timestamp())}.jpg"
            image_url = await self.upload_image_to_supabase(image_data, filename)
            
            if not image_url:
                await processing_msg.edit_text("❌ Error uploading image.")
                return
            
            # Save to database
            user_id = update.effective_user.id
            success = await self.save_note_to_database(user_id, title, tags, extracted_text, image_url)
            
            if success:
                # Format response
                tags_text = " ".join([f"#{tag}" for tag in tags])
                response_text = (
                    "✅ Note saved successfully!\n\n"
                    f"📋 **Title:** {title}\n\n"
                    f"🏷️ **Tags:** {tags_text}\n\n"
                    f"📄 **Content:**\n{extracted_text}"
                )
                
                # Handle message length limit
                if len(response_text) > 4090:
                    max_content = 4090 - len(response_text) + len(extracted_text) - 50
                    truncated_content = extracted_text[:max_content] + "..."
                    response_text = (
                        "✅ Note saved successfully!\n\n"
                        f"📋 **Title:** {title}\n\n"
                        f"🏷️ **Tags:** {tags_text}\n\n"
                        f"📄 **Content:**\n{truncated_content}\n\n"
                        "_Full content saved to database._"
                    )
                
                await processing_msg.edit_text(response_text, parse_mode='Markdown')
            else:
                await processing_msg.edit_text("❌ Error saving note.")
                
        except Exception as e:
            logger.error(f"Error handling photo: {e}")
            if processing_msg:
                try:
                    await processing_msg.edit_text("❌ Error processing image.")
                except:
                    pass
            else:
                await update.message.reply_text("❌ Error processing image.")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle document messages"""
        document = update.message.document
        
        if document.mime_type and document.mime_type.startswith('image/'):
            await self.handle_photo(update, context)
        else:
            await update.message.reply_text("📎 Please send image files only.")

def main():
    """Start the bot"""
    if not all([TELEGRAM_BOT_TOKEN, SUPABASE_URL, SUPABASE_KEY]):
        logger.error("Missing environment variables")
        return
    
    bot = NotesBot()
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", bot.start_command))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("stats", bot.stats_command))
    application.add_handler(MessageHandler(filters.PHOTO, bot.handle_photo))
    application.add_handler(MessageHandler(filters.Document.IMAGE, bot.handle_document))
    
    logger.info("Starting bot...")
    application.run_polling()

if __name__ == '__main__':
    main()