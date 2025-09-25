import os
import io
import base64
import requests
import logging
import json
from datetime import datetime
from typing import Optional, List
import re

import telebot
from supabase import create_client, Client
from PIL import Image
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    """Configuration class for environment variables"""
    TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    SUPABASE_URL = os.getenv('SUPABASE_URL')
    SUPABASE_KEY = os.getenv('SUPABASE_KEY')
    YANDEX_IAM_TOKEN = os.getenv('YANDEX_IAM_TOKEN')
    YANDEX_FOLDER_ID = os.getenv('YANDEX_FOLDER_ID')
    SUPABASE_STORAGE_BUCKET = os.getenv('SUPABASE_STORAGE_BUCKET', 'screenshots')

class YandexVisionOCR:
    """Class for handling Yandex Vision OCR API based on official documentation"""
    
    def __init__(self, iam_token: str, folder_id: str):
        self.iam_token = iam_token
        self.folder_id = folder_id
        self.api_url = "https://ocr.api.cloud.yandex.net/ocr/v1/recognizeText"
    
    def extract_text_from_image(self, image_base64: str, mime_type: str = "JPEG") -> str:
        """
        Extract text from image using Yandex Vision OCR
        Based on: https://yandex.cloud/ru-kz/docs/vision/quickstart
        """
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.iam_token}',
            'x-folder-id': self.folder_id,
            'x-data-logging-enabled': 'true'
        }
        
        # Request payload according to official documentation
        payload = {
            "mimeType": mime_type,
            "languageCodes": ["*"],  # Auto-detect language
            "model": "page",  # Use 'page' model for general text recognition
            "content": image_base64
        }
        
        try:
            logger.info("Sending request to Yandex Vision OCR...")
            response = requests.post(self.api_url, json=payload, headers=headers)
            
            # Log response status
            logger.info(f"OCR API response status: {response.status_code}")
            
            if response.status_code == 401:
                logger.error("Authentication failed. IAM token may be expired.")
                return "Error: IAM token expired. Please refresh your token."
            
            response.raise_for_status()
            result = response.json()
            
            # Extract fullText from the response (primary method)
            if 'result' in result and 'textAnnotation' in result['result']:
                text_annotation = result['result']['textAnnotation']
                
                # Try to get fullText first (recommended)
                full_text = text_annotation.get('fullText', '')
                if full_text:
                    logger.info(f"Successfully extracted text using fullText: {len(full_text)} characters")
                    return full_text.strip()
                
                # Fallback: extract text from blocks
                text_blocks = []
                blocks = text_annotation.get('blocks', [])
                
                for block in blocks:
                    for line in block.get('lines', []):
                        line_text = line.get('text', '')
                        if line_text:
                            text_blocks.append(line_text)
                
                combined_text = '\n'.join(text_blocks)
                if combined_text:
                    logger.info(f"Successfully extracted text using blocks: {len(combined_text)} characters")
                    return combined_text.strip()
            
            logger.warning("No text found in the response")
            return ""
            
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP Error calling Yandex Vision API: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response content: {e.response.text}")
                if e.response.status_code == 401:
                    return "Error: Authentication failed. Please check your IAM token."
                elif e.response.status_code == 403:
                    return "Error: Access denied. Please check your folder permissions."
            return "Error: Failed to process image with OCR service."
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Request Error calling Yandex Vision API: {e}")
            return "Error: Network error while processing image."
            
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {e}")
            return "Error: Invalid response from OCR service."
            
        except Exception as e:
            logger.error(f"Unexpected error processing OCR response: {e}")
            return "Error: Unexpected error during text extraction."

class NoteProcessor:
    """Class for processing extracted text into structured notes"""
    
    @staticmethod
    def generate_title(content: str, max_length: int = 50) -> str:
        """Generate a title from the content"""
        if not content or content.startswith("Error:"):
            return "Untitled Screenshot"
        
        # Clean and get first meaningful sentence
        sentences = re.split(r'[.!?\n]+', content.strip())
        first_sentence = sentences[0].strip() if sentences else content[:max_length]
        
        # Remove extra whitespace and truncate
        title = re.sub(r'\s+', ' ', first_sentence)
        if len(title) > max_length:
            title = title[:max_length-3] + "..."
        
        return title or "Screenshot Note"
    
    @staticmethod
    def extract_tags(content: str) -> List[str]:
        """Extract relevant tags from content"""
        if not content or content.startswith("Error:"):
            return []
        
        # Simple tag extraction based on common patterns
        tags = []
        content_lower = content.lower()
        
        # Common categories
        tag_patterns = {
            'email': ['email', '@', 'mail', 'inbox'],
            'auth': ['password', 'login', 'auth', 'signin', 'signup'],
            'code': ['code', 'programming', 'function', 'class', 'def ', 'var ', 'const ', '{', '}'],
            'meeting': ['meeting', 'call', 'zoom', 'teams', 'conference'],
            'todo': ['todo', 'task', 'deadline', '☐', '□', 'checklist'],
            'finance': ['invoice', 'payment', 'bill', '$', '€', '₽', 'price', 'cost'],
            'error': ['error', 'exception', 'bug', 'failed', 'warning'],
            'document': ['document', 'report', 'pdf', 'doc', 'file'],
            'web': ['http', 'www', 'url', 'website', 'browser'],
            'mobile': ['phone', 'mobile', 'app', 'android', 'ios'],
            'social': ['facebook', 'twitter', 'instagram', 'telegram', 'whatsapp'],
            'date': ['today', 'tomorrow', 'yesterday', '2024', '2025', 'january', 'february']
        }
        
        for tag, patterns in tag_patterns.items():
            if any(pattern in content_lower for pattern in patterns):
                tags.append(tag)
        
        # Extract hashtags if present
        hashtags = re.findall(r'#\w+', content)
        tags.extend([tag[1:].lower() for tag in hashtags])
        
        # Remove duplicates and return
        return list(set(tags))

class SupabaseManager:
    """Class for managing Supabase operations"""
    
    def __init__(self, url: str, key: str, bucket_name: str):
        self.client: Client = create_client(url, key)
        self.bucket_name = bucket_name
    
    def upload_image(self, image_data: bytes, filename: str) -> Optional[str]:
        """Upload image to Supabase storage and return public URL"""
        try:
            # Upload to storage
            result = self.client.storage.from_(self.bucket_name).upload(
                filename, image_data, file_options={"content-type": "image/jpeg"}
            )
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"Error uploading image: {result.error}")
                return None
            
            # Get public URL
            public_url = self.client.storage.from_(self.bucket_name).get_public_url(filename)
            return public_url
            
        except Exception as e:
            logger.error(f"Error uploading image to Supabase: {e}")
            return None
    
    def save_note(self, user_id: int, title: str, tags: List[str], content: str, 
                  image_url: Optional[str] = None) -> Optional[dict]:
        """Save note to Supabase database"""
        try:
            data = {
                'user_id': user_id,
                'title': title,
                'tags': tags,
                'content': content,
                'image_url': image_url,
                'created_at': datetime.now().isoformat()
            }
            
            result = self.client.table('notes').insert(data).execute()
            
            if result.data:
                return result.data[0]
            else:
                logger.error(f"Error saving note: No data returned")
                return None
                
        except Exception as e:
            logger.error(f"Error saving note to Supabase: {e}")
            return None
    
    def get_user_notes(self, user_id: int, limit: int = 10) -> List[dict]:
        """Get user's recent notes"""
        try:
            result = self.client.table('notes').select('*').eq('user_id', user_id).order('created_at', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error fetching user notes: {e}")
            return []

class TelegramOCRBot:
    """Main bot class"""
    
    def __init__(self, config: Config):
        self.bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
        self.ocr = YandexVisionOCR(config.YANDEX_IAM_TOKEN, config.YANDEX_FOLDER_ID)
        self.db = SupabaseManager(config.SUPABASE_URL, config.SUPABASE_KEY, config.SUPABASE_STORAGE_BUCKET)
        self.note_processor = NoteProcessor()
        
        # Register handlers
        self.register_handlers()
    
    def register_handlers(self):
        """Register bot command and message handlers"""
        
        @self.bot.message_handler(commands=['start', 'help'])
        def send_welcome(message):
            welcome_text = """
🤖 **Screenshot OCR Bot**

Send me a screenshot and I'll:
📝 Extract all text using Yandex Vision OCR
🏷️ Generate relevant tags
📋 Create a structured note
💾 Save everything to your personal database

**Commands:**
/start - Show this help message
/recent - Show your recent notes (last 10)
/token - Show IAM token status

**Supported formats:** JPEG, PNG, PDF (up to 10MB)

Just send me any image to get started!
            """
            self.bot.reply_to(message, welcome_text, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['token'])
        def check_token_status(message):
            """Check IAM token status"""
            try:
                # Simple test request to check token validity
                test_payload = {
                    "mimeType": "JPEG",
                    "languageCodes": ["*"],
                    "model": "page",
                    "content": ""  # Empty content for test
                }
                
                headers = {
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {self.ocr.iam_token}',
                    'x-folder-id': self.ocr.folder_id
                }
                
                response = requests.post(self.ocr.api_url, json=test_payload, headers=headers, timeout=5)
                
                if response.status_code == 401:
                    status = "❌ **Token Status: EXPIRED**\n\nPlease refresh your IAM token using:\n`python yandex_iam_helper.py`"
                elif response.status_code == 400:  # Expected for empty content
                    status = "✅ **Token Status: VALID**\n\nYour IAM token is working correctly!"
                else:
                    status = f"⚠️ **Token Status: UNKNOWN**\n\nResponse code: {response.status_code}"
                
            except requests.exceptions.Timeout:
                status = "⚠️ **Token Status: TIMEOUT**\n\nCouldn't verify token due to network timeout."
            except Exception as e:
                status = f"❌ **Token Status: ERROR**\n\nError: {str(e)}"
            
            self.bot.reply_to(message, status, parse_mode='Markdown')
        
        @self.bot.message_handler(commands=['recent'])
        def show_recent_notes(message):
            user_id = message.from_user.id
            notes = self.db.get_user_notes(user_id)
            
            if not notes:
                self.bot.reply_to(message, "You don't have any notes yet. Send me a screenshot to create your first note!")
                return
            
            response = "📋 **Your Recent Notes:**\n\n"
            for i, note in enumerate(notes, 1):
                tags_str = ", ".join(note.get('tags', []))
                response += f"{i}. **{note['title']}**\n"
                if tags_str:
                    response += f"🏷️ Tags: {tags_str}\n"
                response += f"📅 {note['created_at'][:10]}\n\n"
            
            self.bot.reply_to(message, response, parse_mode='Markdown')
        
        @self.bot.message_handler(content_types=['photo'])
        def handle_photo(message):
            try:
                # Notify user that processing started
                processing_msg = self.bot.reply_to(message, "📸 Processing your screenshot...")
                
                # Get the highest resolution photo
                photo = message.photo[-1]
                file_info = self.bot.get_file(photo.file_id)
                downloaded_file = self.bot.download_file(file_info.file_path)
                
                # Convert to base64 for Yandex Vision
                image_base64 = base64.b64encode(downloaded_file).decode('utf-8')
                
                # Determine MIME type from file extension
                mime_type = "JPEG"  # Default
                if file_info.file_path.lower().endswith('.png'):
                    mime_type = "PNG"
                elif file_info.file_path.lower().endswith('.pdf'):
                    mime_type = "PDF"
                
                # Extract text using OCR
                self.bot.edit_message_text("🔍 Extracting text with Yandex Vision OCR...", 
                                         message.chat.id, processing_msg.message_id)
                
                extracted_text = self.ocr.extract_text_from_image(image_base64, mime_type)
                
                # Check if extraction failed
                if not extracted_text:
                    self.bot.edit_message_text("❌ Could not extract text from the image. Please try with a clearer screenshot.", 
                                             message.chat.id, processing_msg.message_id)
                    return
                
                if extracted_text.startswith("Error:"):
                    self.bot.edit_message_text(f"❌ {extracted_text}", 
                                             message.chat.id, processing_msg.message_id)
                    return
                
                # Process the note
                self.bot.edit_message_text("📝 Generating note...", 
                                         message.chat.id, processing_msg.message_id)
                
                title = self.note_processor.generate_title(extracted_text)
                tags = self.note_processor.extract_tags(extracted_text)
                
                # Upload image to storage
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{message.from_user.id}_{timestamp}.jpg"
                image_url = self.db.upload_image(downloaded_file, filename)
                
                # Save to database
                note = self.db.save_note(
                    user_id=message.from_user.id,
                    title=title,
                    tags=tags,
                    content=extracted_text,
                    image_url=image_url
                )
                
                if note:
                    # Format response
                    tags_str = ", ".join(tags) if tags else "None"
                    content_preview = extracted_text[:300] + "..." if len(extracted_text) > 300 else extracted_text
                    
                    response = f"""
✅ **Note Created Successfully!**

📋 **Title:** {title}
🏷️ **Tags:** {tags_str}
📝 **Content Preview:**
```
{content_preview}
```

💾 Note saved to your database!
📊 Total characters extracted: {len(extracted_text)}
                    """
                    
                    self.bot.edit_message_text(response, message.chat.id, processing_msg.message_id, parse_mode='Markdown')
                else:
                    self.bot.edit_message_text("❌ Error saving note to database. Please try again.", 
                                             message.chat.id, processing_msg.message_id)
                
            except Exception as e:
                logger.error(f"Error processing photo: {e}")
                try:
                    self.bot.edit_message_text("❌ An error occurred while processing your screenshot. Please try again.", 
                                             message.chat.id, processing_msg.message_id)
                except:
                    self.bot.reply_to(message, "❌ An error occurred while processing your screenshot. Please try again.")
        
        @self.bot.message_handler(content_types=['document'])
        def handle_document(message):
            """Handle PDF documents"""
            if message.document.mime_type == 'application/pdf':
                try:
                    processing_msg = self.bot.reply_to(message, "📄 Processing your PDF...")
                    
                    file_info = self.bot.get_file(message.document.file_id)
                    downloaded_file = self.bot.download_file(file_info.file_path)
                    
                    # Convert to base64
                    pdf_base64 = base64.b64encode(downloaded_file).decode('utf-8')
                    
                    # Extract text using OCR
                    self.bot.edit_message_text("🔍 Extracting text from PDF...", 
                                             message.chat.id, processing_msg.message_id)
                    
                    extracted_text = self.ocr.extract_text_from_image(pdf_base64, "PDF")
                    
                    if not extracted_text or extracted_text.startswith("Error:"):
                        self.bot.edit_message_text("❌ Could not extract text from the PDF.", 
                                                 message.chat.id, processing_msg.message_id)
                        return
                    
                    # Process and save note (same as photo handler)
                    title = self.note_processor.generate_title(extracted_text)
                    tags = self.note_processor.extract_tags(extracted_text)
                    
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"pdf_{message.from_user.id}_{timestamp}.pdf"
                    file_url = self.db.upload_image(downloaded_file, filename)
                    
                    note = self.db.save_note(
                        user_id=message.from_user.id,
                        title=title,
                        tags=tags,
                        content=extracted_text,
                        image_url=file_url
                    )
                    
                    if note:
                        tags_str = ", ".join(tags) if tags else "None"
                        content_preview = extracted_text[:300] + "..." if len(extracted_text) > 300 else extracted_text
                        
                        response = f"""
✅ **PDF Note Created Successfully!**

📋 **Title:** {title}
🏷️ **Tags:** {tags_str}
📝 **Content Preview:**
```
{content_preview}
```

💾 Note saved to your database!
📊 Total characters extracted: {len(extracted_text)}
                        """
                        
                        self.bot.edit_message_text(response, message.chat.id, processing_msg.message_id, parse_mode='Markdown')
                    
                except Exception as e:
                    logger.error(f"Error processing PDF: {e}")
                    self.bot.reply_to(message, "❌ Error processing PDF. Please try again.")
            else:
                self.bot.reply_to(message, "📄 I can only process PDF documents. Please send an image or PDF file.")
        
        @self.bot.message_handler(func=lambda message: True)
        def handle_text(message):
            help_text = """
Please send me a screenshot, image, or PDF to analyze. 

**Supported formats:**
📸 JPEG, PNG images
📄 PDF documents
📏 Maximum size: 10MB

Use /help for more information.
            """
            self.bot.reply_to(message, help_text)
    
    def run(self):
        """Start the bot"""
        logger.info("Starting Telegram OCR Bot with Yandex Cloud Vision...")
        try:
            self.bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            logger.error(f"Bot error: {e}")
            raise

# Database schema (run this in Supabase SQL editor):
"""
-- Create notes table
CREATE TABLE notes (
    id SERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    title TEXT NOT NULL,
    tags TEXT[] DEFAULT '{}',
    content TEXT NOT NULL,
    image_url TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Create indexes for better performance
CREATE INDEX idx_notes_user_id ON notes(user_id);
CREATE INDEX idx_notes_created_at ON notes(created_at);
CREATE INDEX idx_notes_tags ON notes USING GIN(tags);

-- Row Level Security (optional, for multi-tenant security)
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Users can only see their own notes" ON notes
    FOR ALL USING (user_id = current_setting('app.current_user_id')::bigint);
"""

if __name__ == "__main__":
    # Validate configuration
    config = Config()
    
    required_vars = [
        'TELEGRAM_BOT_TOKEN',
        'SUPABASE_URL', 
        'SUPABASE_KEY',
        'YANDEX_IAM_TOKEN',
        'YANDEX_FOLDER_ID'
    ]
    
    missing_vars = [var for var in required_vars if not getattr(config, var)]
    
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        print("\n❌ Configuration Error!")
        print(f"Missing environment variables: {', '.join(missing_vars)}")
        print("\n📋 Please check your .env file and ensure all required variables are set:")
        for var in missing_vars:
            print(f"  {var}=your_{var.lower()}_here")
        print("\n💡 Run 'python yandex_iam_helper.py' to generate IAM token")
        exit(1)
    
    # Create and run bot
    try:
        bot = TelegramOCRBot(config)
        print("🚀 Bot started successfully!")
        print("📱 Send /start to your bot to begin")
        bot.run()
    except KeyboardInterrupt:
        print("\n👋 Bot stopped by user")
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        print(f"\n❌ Failed to start bot: {e}")
        exit(1)