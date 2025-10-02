import os
import logging
import asyncio
import base64
from io import BytesIO
from datetime import datetime
from typing import Optional, Dict, Any

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from supabase import create_client, Client
from openai import OpenAI
import json

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class NotesBot:
    def __init__(self):
        # Initialize clients
        self.supabase: Client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_KEY")
        )
        self.openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        # Telegram bot token
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        
        # Language translations
        self.translations = {
            "ru": {
                "welcome": "👋 Добро пожаловать в Screenshot Notes Bot!\n\n📸 Отправьте мне любой скриншот, и я проанализирую его, чтобы создать структурированные заметки с:\n• Заголовком\n• Тегами\n• Содержимым (извлеченный текст)\n\n🌐 Для смены языка используйте /language\n\n📋 Доступные команды:\n/start - Начать работу с ботом\n/help - Показать справку\n/list - Показать ваши последние заметки\n/language - Сменить язык\n\nПросто отправьте изображение, и я сделаю всё остальное!",
                "help": "🤖 Справка Screenshot Notes Bot\n\n📋 Команды:\n/start - Начать работу с ботом\n/help - Показать эту справку\n/list - Показать ваши последние заметки\n/language - Сменить язык\n\n📸 Как использовать:\n1. Отправьте мне любой скриншот\n2. Я проанализирую его с помощью ИИ\n3. Вы получите структурированные заметки с заголовком, тегами и содержимым\n\n💾 Все ваши заметки сохраняются безопасно!",
                "no_notes": "📝 У вас пока нет заметок. Отправьте мне скриншот, чтобы начать!",
                "recent_notes": "📋 Ваши последние заметки:\n\n",
                "error_fetching": "❌ Ошибка при получении заметок. Попробуйте позже.",
                "processing": "🔄 Обрабатываю ваш скриншот...",
                "uploading": "📤 Загружаю изображение...",
                "analyzing": "🤖 Анализирую с помощью ИИ...",
                "saving": "💾 Сохраняю заметки...",
                "upload_failed": "❌ Не удалось загрузить изображение. Попробуйте снова.",
                "analysis_failed": "❌ Не удалось проанализировать изображение. Попробуйте снова.",
                "save_failed": "❌ Не удалось сохранить заметки. Попробуйте снова.",
                "success": "✅ **Скриншот успешно проанализирован!**\n\n📝 **Заголовок:** {title}\n\n🏷️ **Теги:** {tags}\n\n📄 **Содержимое:**\n{content}\n\n💾 Заметка сохранена в вашу коллекцию!\n🔗 **Изображение:** {image_url}",
                "error_processing": "❌ Произошла ошибка при обработке изображения. Попробуйте снова.",
                "send_image": "📸 Пожалуйста, отправьте мне скриншот или изображение для анализа.\n\nЯ могу извлечь текст и создать структурированные заметки из:\n• Скриншотов\n• Документов\n• Фрагментов кода\n• Любых изображений с текстом",
                "language_selection": "🌐 Выберите язык / Тілді таңдаңыз / Choose language:\n\n🇷🇺 Русский - /lang_ru\n🇰🇿 Қазақша - /lang_kz\n🇺🇸 English - /lang_en",
                "language_changed": "🌐 Язык изменен на русский"
            },
            "kz": {
                "welcome": "👋 Screenshot Notes Bot-қа қош келдіңіз!\n\n📸 Маған кез келген скриншот жіберіңіз, мен оны талдап, құрылымдалған жазбаларды жасаймын:\n• Тақырыбы\n• Тегтері\n• Мазмұны (алынған мәтін)\n\n🌐 Тілді өзгерту үшін /language пайдаланыңыз\n\n📋 Қол жетімді команда:\n/start - Ботпен жұмысты бастау\n/help - Анықтама көрсету\n/list - Соңғы жазбаларыңызды көрсету\n/language - Тілді өзгерту\n\nТек суретті жіберіңіз, қалғанын мен жасаймын!",
                "help": "🤖 Screenshot Notes Bot анықтамасы\n\n📋 Командалар:\n/start - Ботпен жұмысты бастау\n/help - Осы анықтаманы көрсету\n/list - Соңғы жазбаларыңызды көрсету\n/language - Тілді өзгерту\n\n📸 Қалай пайдалану:\n1. Маған кез келген скриншот жіберіңіз\n2. Мен оны AI арқылы талдаймын\n3. Сіз тақырыбы, тегтері және мазмұны бар құрылымдалған жазбаларды аласыз\n\n💾 Барлық жазбаларыңыз қауіпсіз сақталады!",
                "no_notes": "📝 Сізде әлі ешқандай жазба жоқ. Бастау үшін маған скриншот жіберіңіз!",
                "recent_notes": "📋 Сіздің соңғы жазбаларыңыз:\n\n",
                "error_fetching": "❌ Жазбаларды алу кезінде қате. Кейінірек көріңіз.",
                "processing": "🔄 Сіздің скриншотыңызды өңдеп жатырмын...",
                "uploading": "📤 Суретті жүктеп жатырмын...",
                "analyzing": "🤖 AI арқылы талдап жатырмын...",
                "saving": "💾 Жазбаларды сақтап жатырмын...",
                "upload_failed": "❌ Суретті жүктеу мүмкін болмады. Қайталап көріңіз.",
                "analysis_failed": "❌ Суретті талдау мүмкін болмады. Қайталап көріңіз.",
                "save_failed": "❌ Жазбаларды сақтау мүмкін болмады. Қайталап көріңіз.",
                "success": "✅ **Скриншот сәтті талданды!**\n\n📝 **Тақырыбы:** {title}\n\n🏷️ **Тегтер:** {tags}\n\n📄 **Мазмұны:**\n{content}\n\n💾 Жазба сіздің коллекцияңызға сақталды!\n🔗 **Сурет:** {image_url}",
                "error_processing": "❌ Суретті өңдеу кезінде қате орын алды. Қайталап көріңіз.",
                "send_image": "📸 Талдау үшін маған скриншот немесе сурет жіберіңіз.\n\nМен мұнан мәтін алып, құрылымдалған жазбалар жасай аламын:\n• Скриншоттар\n• Құжаттар\n• Код фрагменттері\n• Мәтіні бар кез келген сурет",
                "language_selection": "🌐 Выберите язык / Тілді таңдаңыз / Choose language:\n\n🇷🇺 Русский - /lang_ru\n🇰🇿 Қазақша - /lang_kz\n🇺🇸 English - /lang_en",
                "language_changed": "🌐 Тіл қазақ тіліне өзгертілді"
            },
            "en": {
                "welcome": "👋 Welcome to Screenshot Notes Bot!\n\n📸 Send me any screenshot and I'll analyze it to create structured notes with:\n• Title\n• Tags\n• Content (extracted text)\n\n🌐 Use /language to change language\n\n📋 Available commands:\n/start - Start the bot\n/help - Show help information\n/list - Show your recent notes\n/language - Change language\n\nJust send an image and I'll do the rest!",
                "help": "🤖 Screenshot Notes Bot Help\n\n📋 Commands:\n/start - Start the bot\n/help - Show this help message\n/list - Show your recent notes\n/language - Change language\n\n📸 How to use:\n1. Send me any screenshot\n2. I'll analyze it with AI\n3. You'll get structured notes with title, tags, and content\n\n💾 All your notes are saved securely!",
                "no_notes": "📝 You don't have any notes yet. Send me a screenshot to get started!",
                "recent_notes": "📋 Your recent notes:\n\n",
                "error_fetching": "❌ Error fetching your notes. Please try again later.",
                "processing": "🔄 Processing your screenshot...",
                "uploading": "📤 Uploading image...",
                "analyzing": "🤖 Analyzing with AI...",
                "saving": "💾 Saving notes...",
                "upload_failed": "❌ Failed to upload image. Please try again.",
                "analysis_failed": "❌ Failed to analyze image. Please try again.",
                "save_failed": "❌ Failed to save notes. Please try again.",
                "success": "✅ **Screenshot analyzed successfully!**\n\n📝 **Title:** {title}\n\n🏷️ **Tags:** {tags}\n\n📄 **Content:**\n{content}\n\n💾 Note saved to your collection!\n🔗 **Image:** {image_url}",
                "error_processing": "❌ An error occurred while processing your image. Please try again.",
                "send_image": "📸 Please send me a screenshot or image to analyze.\n\nI can extract text and create structured notes from:\n• Screenshots\n• Documents\n• Code snippets\n• Any image with text",
                "language_selection": "🌐 Выберите язык / Тілді таңдаңыз / Choose language:\n\n🇷🇺 Русский - /lang_ru\n🇰🇿 Қазақша - /lang_kz\n🇺🇸 English - /lang_en",
                "language_changed": "🌐 Language changed to English"
            }
        }
        
    async def get_user_language(self, user_id: int) -> str:
        """Get user's preferred language, default to Russian"""
        try:
            response = self.supabase.table("user_settings").select("language").eq("user_id", user_id).execute()
            if response.data:
                return response.data[0]["language"]
            return "ru"  # Default to Russian
        except Exception as e:
            logger.error(f"Error getting user language: {e}")
            return "ru"

    async def set_user_language(self, user_id: int, language: str) -> bool:
        """Set user's preferred language"""
        try:
            # Try to update existing record
            response = self.supabase.table("user_settings").select("user_id").eq("user_id", user_id).execute()
            
            if response.data:
                # Update existing
                self.supabase.table("user_settings").update({"language": language}).eq("user_id", user_id).execute()
            else:
                # Insert new
                self.supabase.table("user_settings").insert({"user_id": user_id, "language": language}).execute()
            return True
        except Exception as e:
            logger.error(f"Error setting user language: {e}")
            return False

    def get_text(self, user_lang: str, key: str, **kwargs) -> str:
        """Get translated text for user's language"""
        text = self.translations.get(user_lang, self.translations["ru"]).get(key, key)
        if kwargs:
            return text.format(**kwargs)
        return text

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /start command"""
        user_id = update.effective_user.id
        user_lang = await self.get_user_language(user_id)
        welcome_message = self.get_text(user_lang, "welcome")
        await update.message.reply_text(welcome_message)

    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /help command"""
        user_id = update.effective_user.id
        user_lang = await self.get_user_language(user_id)
        help_message = self.get_text(user_lang, "help")
        await update.message.reply_text(help_message)

    async def language_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /language command"""
        user_id = update.effective_user.id
        user_lang = await self.get_user_language(user_id)
        language_message = self.get_text(user_lang, "language_selection")
        await update.message.reply_text(language_message)

    async def set_language_ru(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set language to Russian"""
        user_id = update.effective_user.id
        await self.set_user_language(user_id, "ru")
        message = self.get_text("ru", "language_changed")
        await update.message.reply_text(message)

    async def set_language_kz(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set language to Kazakh"""
        user_id = update.effective_user.id
        await self.set_user_language(user_id, "kz")
        message = self.get_text("kz", "language_changed")
        await update.message.reply_text(message)

    async def set_language_en(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Set language to English"""
        user_id = update.effective_user.id
        await self.set_user_language(user_id, "en")
        message = self.get_text("en", "language_changed")
        await update.message.reply_text(message)

    async def list_notes_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle /list command to show recent notes"""
        user_id = update.effective_user.id
        user_lang = await self.get_user_language(user_id)
        
        try:
            # Get recent notes for user
            response = self.supabase.table("notes").select("*").eq("user_id", user_id).order("created_at", desc=True).limit(5).execute()
            
            if not response.data:
                await update.message.reply_text(self.get_text(user_lang, "no_notes"))
                return
            
            message = self.get_text(user_lang, "recent_notes")
            for i, note in enumerate(response.data, 1):
                created_at = datetime.fromisoformat(note['created_at'].replace('Z', '+00:00'))
                formatted_date = created_at.strftime("%Y-%m-%d %H:%M")
                
                # Get tags for this note
                tags = await self.get_note_tags(note['id'])
                tags_str = ', '.join(tags) if tags else 'No tags'
                
                message += f"{i}. **{note['title']}**\n"
                message += f"   📅 {formatted_date}\n"
                message += f"   🏷️ {tags_str}\n\n"
            
            await update.message.reply_text(message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error fetching notes: {e}")
            await update.message.reply_text(self.get_text(user_lang, "error_fetching"))

    async def upload_image_to_supabase(self, image_data: bytes, filename: str) -> Optional[str]:
        """Upload image to Supabase storage"""
        try:
            # Upload to Supabase storage
            response = self.supabase.storage.from_("screenshots").upload(filename, image_data)
            
            if response:
                # Get public URL
                public_url = self.supabase.storage.from_("screenshots").get_public_url(filename)
                return public_url
            return None
            
        except Exception as e:
            logger.error(f"Error uploading image to Supabase: {e}")
            return None

    async def analyze_image_with_openai(self, image_data: bytes) -> Optional[Dict[str, Any]]:
        """Analyze image using OpenAI Vision API"""
        try:
            # Convert image to base64
            base64_image = base64.b64encode(image_data).decode('utf-8')
            
            prompt = """
            Please analyze this screenshot/image and extract structured information in the following JSON format:
            
            {
                "title": "A descriptive title for the content (max 100 chars)",
                "tags": ["tag1", "tag2", "tag3"],
                "content": "All readable text from the image, organized and formatted clearly"
            }
            
            Guidelines:
            - Title should be descriptive and capture the main topic/purpose
            - Tags should be relevant keywords (max 3 tags)
            - Content should include ALL readable text, maintaining structure when possible
            - If it's a code screenshot, preserve code formatting
            - If it's a document, maintain paragraph structure
            - If text is unclear, indicate with [unclear text]
            
            Return only valid JSON.
            """
            
            response = self.openai_client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "high"
                                }
                            }
                        ]
                    }
                ]
            )
            
            # Parse JSON response
            content = response.choices[0].message.content.strip()
            
            # Clean up response (remove markdown code blocks if present)
            if content.startswith('```json'):
                content = content[7:-3].strip()
            elif content.startswith('```'):
                content = content[3:-3].strip()
            
            return json.loads(content)
            
        except Exception as e:
            logger.error(f"Error analyzing image with OpenAI: {e}")
            return None

    async def save_note_to_db(self, user_id: int, username: str, note_data: Dict[str, Any], image_url: str) -> bool:
        """Save note to Supabase database with separate tags table"""
        try:
            # Prepare data for notes table (without tags)
            note_db_data = {
                "user_id": user_id,
                "username": username,
                "title": note_data["title"],
                "content": note_data["content"],
                "image_url": image_url,
                "created_at": datetime.now().isoformat()
            }
            
            # Insert into notes table and get the ID
            notes_response = self.supabase.table("notes").insert(note_db_data).execute()
            
            if not notes_response.data or len(notes_response.data) == 0:
                return False
                
            note_id = notes_response.data[0]["id"]
            
            # Insert tags into note_tags table
            if note_data.get("tags"):
                tag_data = []
                for tag in note_data["tags"]:
                    if tag.strip():  # Only add non-empty tags
                        tag_data.append({
                            "note_id": note_id,
                            "tag": tag.strip()
                        })
                
                if tag_data:  # Only insert if there are valid tags
                    self.supabase.table("note_tags").insert(tag_data).execute()
            
            return True
            
        except Exception as e:
            logger.error(f"Error saving note to database: {e}")
            return False

    async def get_note_tags(self, note_id: int) -> list:
        """Get all tags for a specific note"""
        try:
            response = self.supabase.table("note_tags").select("tag").eq("note_id", note_id).execute()
            return [tag_row["tag"] for tag_row in response.data] if response.data else []
        except Exception as e:
            logger.error(f"Error fetching note tags: {e}")
            return []

    async def handle_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming images"""
        user_id = update.effective_user.id
        username = update.effective_user.username or f"user_{user_id}"
        user_lang = await self.get_user_language(user_id)
        
        # Send processing message
        processing_msg = await update.message.reply_text(self.get_text(user_lang, "processing"))
        
        try:
            # Get the largest photo size
            photo = update.message.photo[-1]
            
            # Download image
            file = await photo.get_file()
            image_data = await file.download_as_bytearray()
            
            # Update processing message
            await processing_msg.edit_text(self.get_text(user_lang, "uploading"))
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            filename = f"{user_id}{timestamp}.jpg"
            
            # Upload to Supabase storage
            image_url = await self.upload_image_to_supabase(bytes(image_data), filename)
            if not image_url:
                await processing_msg.edit_text(self.get_text(user_lang, "upload_failed"))
                return
            
            # Update processing message
            await processing_msg.edit_text(self.get_text(user_lang, "analyzing"))
            
            # Analyze with OpenAI
            analysis_result = await self.analyze_image_with_openai(bytes(image_data))
            if not analysis_result:
                await processing_msg.edit_text(self.get_text(user_lang, "analysis_failed"))
                return
            
            # Update processing message
            await processing_msg.edit_text(self.get_text(user_lang, "saving"))
            
            # Save to database
            saved = await self.save_note_to_db(user_id, username, analysis_result, image_url)
            if not saved:
                await processing_msg.edit_text(self.get_text(user_lang, "save_failed"))
                return
            
            # Format response message with image URL
            content_preview = analysis_result['content'][:1000]
            if len(analysis_result['content']) > 1000:
                content_preview += "..."
                
            response_message = self.get_text(
                user_lang, 
                "success",
                title=analysis_result['title'],
                tags=', '.join(analysis_result['tags']),
                content=content_preview,
                image_url=image_url
            )
            
            await processing_msg.edit_text(response_message, parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Error handling image: {e}")
            await processing_msg.edit_text(self.get_text(user_lang, "error_processing"))

    async def handle_non_image(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle non-image messages"""
        user_id = update.effective_user.id
        user_lang = await self.get_user_language(user_id)
        await update.message.reply_text(self.get_text(user_lang, "send_image"))

    def create_application(self) -> Application:
        """Create and configure the Telegram bot application"""
        application = Application.builder().token(self.bot_token).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", self.start_command))
        application.add_handler(CommandHandler("help", self.help_command))
        application.add_handler(CommandHandler("list", self.list_notes_command))
        application.add_handler(CommandHandler("language", self.language_command))
        application.add_handler(CommandHandler("lang_ru", self.set_language_ru))
        application.add_handler(CommandHandler("lang_kz", self.set_language_kz))
        application.add_handler(CommandHandler("lang_en", self.set_language_en))
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_image))
        application.add_handler(MessageHandler(~filters.PHOTO, self.handle_non_image))
        
        return application

def setup_database():
    """Setup database table if it doesn't exist"""
    try:
        # This would typically be done via Supabase dashboard or migrations
        # But here's the SQL for reference:
        create_tables_sql = """
        -- Create notes table (removed tags array column)
        CREATE TABLE IF NOT EXISTS notes (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            username VARCHAR(255),
            title VARCHAR(500) NOT NULL,
            content TEXT NOT NULL,
            image_url TEXT NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        -- Create note_tags table for normalized tag storage
        CREATE TABLE IF NOT EXISTS note_tags (
            id SERIAL PRIMARY KEY,
            note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
            tag VARCHAR(100) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        -- Create user_settings table for language preferences
        CREATE TABLE IF NOT EXISTS user_settings (
            id SERIAL PRIMARY KEY,
            user_id BIGINT UNIQUE NOT NULL,
            language VARCHAR(2) DEFAULT 'ru',
            created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
        );
        
        -- Create indexes for better performance
        CREATE INDEX IF NOT EXISTS idx_notes_user_id ON notes(user_id);
        CREATE INDEX IF NOT EXISTS idx_notes_created_at ON notes(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_note_tags_note_id ON note_tags(note_id);
        CREATE INDEX IF NOT EXISTS idx_note_tags_tag ON note_tags(tag);
        CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id);
        
        -- Create unique constraint to prevent duplicate tags for the same note
        CREATE UNIQUE INDEX IF NOT EXISTS idx_note_tags_unique ON note_tags(note_id, tag);
        """
        
        print("Database tables should be created manually in Supabase with the following structure:")
        print(create_tables_sql)
        
    except Exception as e:
        logger.error(f"Database setup note: {e}")

def main():
    """Main function to run the bot"""
    # Check environment variables
    required_vars = ["TELEGRAM_BOT_TOKEN", "SUPABASE_URL", "SUPABASE_KEY", "OPENAI_API_KEY"]
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return
    
    # Setup database (informational)
    # setup_database()
    
    # Create and run bot
    bot = NotesBot()
    application = bot.create_application()
    
    logger.info("Starting Telegram Screenshot Notes Bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()