from config import CODE, TOKEN
from modules import COURSES
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Set up logging
logging.basicConfig(level=logging.INFO)

# Define the access code
ACCESS_CODE = CODE

# Store authorized users
AUTHORIZED_USERS = set()
# Store quiz results
RESULTS_FILE = "quiz_results.json"

# Load existing results from file
def load_results():
    try:
        with open(RESULTS_FILE, "r") as file:
            results = json.load(file)
            if not isinstance(results, dict):
                logging.warning("Неверный формат файла результатов. Начинаем с нуля.")
                return {}
            logging.info("Результаты успешно загружены.")
            return results
    except FileNotFoundError:
        logging.warning("Файл результатов не найден. Создаем новый.")
        return {}
    except json.JSONDecodeError:
        logging.error("Файл результатов поврежден. Начинаем с нуля.")
        return {}

# Save results to file
def save_results(results):
    try:
        with open(RESULTS_FILE, "w") as file:
            json.dump(results, file)
            logging.info("Результаты успешно сохранены.")
    except Exception as e:
        logging.error(f"Не удалось сохранить результаты: {e}")

USER_RESULTS = load_results()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить приветственное сообщение и запросить код доступа."""
    await update.message.reply_text(
        "Добро пожаловать в Образовательного Бота! Пожалуйста, введите код доступа, чтобы продолжить:"
    )

async def check_access_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверить код доступа и предоставить доступ, если он верен."""
    user_id = str(update.message.from_user.id)  # Убедитесь, что user_id - строка
    if user_id in AUTHORIZED_USERS:
        await update.message.reply_text("Вы уже авторизованы! Используйте /modules, чтобы просмотреть курсы.")
        return

    if update.message.text == ACCESS_CODE:
        AUTHORIZED_USERS.add(user_id)
        await update.message.reply_text(
            "Доступ предоставлен! Используйте /modules, чтобы просмотреть доступные курсы."
        )
    else:
        await update.message.reply_text("Неверный код доступа. Попробуйте снова.")

async def show_modules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить сообщение со списком модулей."""
    user_id = str(update.message.from_user.id)  # Убедитесь, что user_id - строка
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("Пожалуйста, сначала введите правильный код доступа.")
        return

    keyboard = [
        [InlineKeyboardButton(module, callback_data=module)] for module in COURSES.keys()
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите модуль:', reply_markup=reply_markup)

async def module_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать уроки в выбранном модуле."""
    query = update.callback_query
    await query.answer()
    module_name = query.data
    
    if module_name in COURSES:
        lessons = COURSES[module_name]
        keyboard = [
            [InlineKeyboardButton(lesson, callback_data=f"{module_name}:{lesson}")]
            for lesson in lessons.keys()
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            text=f"Вы выбрали {module_name}. Пожалуйста, выберите урок:",
            reply_markup=reply_markup
        )

async def lesson_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить детали урока: видео, текст, изображение и файл."""
    query = update.callback_query
    await query.answer()
    module_name, lesson_name = query.data.split(":")

    if module_name in COURSES and lesson_name in COURSES[module_name]:
        lesson = COURSES[module_name][lesson_name]

        # Отправить изображение с текстом, если доступно
        if "image" in lesson and lesson["image"]:
            with open(lesson['image'], 'rb') as image_file:
                await context.bot.send_photo(
                    chat_id=query.message.chat_id,
                    photo=image_file,
                    caption=f"Урок: {lesson_name}\n{lesson['text']}"
                )
        else:
            await context.bot.send_message(
                chat_id=query.message.chat_id,
                text=f"Урок: {lesson_name}\n{lesson['text']}"
            )

        # Отправить видеофайл, если доступно
        if "video" in lesson and lesson["video"]:
            with open(lesson['video'], 'rb') as video_file:
                await context.bot.send_video(
                    chat_id=query.message.chat_id,
                    video=video_file
                )

        # Отправить файл, если доступно
        if "file" in lesson and lesson["file"]:
            await context.bot.send_document(
                chat_id=query.message.chat_id,
                document=lesson['file']
            )

        # Предложить пройти тест
        keyboard = [[InlineKeyboardButton("Пройти тест", callback_data=f"quiz:{module_name}:{lesson_name}")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text="Хотите проверить свои знания?",
            reply_markup=reply_markup
        )

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начать тест для выбранного урока."""
    query = update.callback_query
    await query.answer()
    _, module_name, lesson_name = query.data.split(":")

    if module_name in COURSES and lesson_name in COURSES[module_name]:
        quiz = COURSES[module_name][lesson_name].get("quiz", [])
        if not quiz:
            await query.edit_message_text("Для этого урока нет теста.")
            return

        context.user_data["quiz"] = quiz
        context.user_data["quiz_index"] = 0
        context.user_data["correct_answers"] = 0
        context.user_data["current_test"] = f"{module_name}:{lesson_name}"

        await send_quiz_question(update, context)

async def send_quiz_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отправить следующий вопрос теста."""
    quiz = context.user_data.get("quiz", [])
    index = context.user_data.get("quiz_index", 0)

    if index < len(quiz):
        question = quiz[index]
        keyboard = [
            [InlineKeyboardButton(option, callback_data=f"answer:{option}")]
            for option in question["options"]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=question["question"],
            reply_markup=reply_markup
        )
    else:
        await show_quiz_results(update, context)

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработать ответ пользователя на вопрос теста."""
    query = update.callback_query
    await query.answer()

    answer = query.data.split(":")[1]
    quiz = context.user_data.get("quiz", [])
    index = context.user_data.get("quiz_index", 0)

    if index < len(quiz):
        correct_answer = quiz[index]["answer"]
        if answer == correct_answer:
            context.user_data["correct_answers"] += 1

        context.user_data["quiz_index"] += 1
        await send_quiz_question(update, context)

async def show_quiz_results(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать результаты теста пользователя."""
    correct_answers = context.user_data.get("correct_answers", 0)
    total_questions = len(context.user_data.get("quiz", []))
    user_id = str(update.effective_user.id)  # Убедитесь, что user_id - строка
    current_test = context.user_data.get("current_test")

    if user_id not in USER_RESULTS:
        USER_RESULTS[user_id] = {}

    if current_test in USER_RESULTS[user_id]:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=f"Вы уже прошли тест для {current_test}. Результаты не записаны повторно."
        )
        return

    USER_RESULTS[user_id][current_test] = {
        "correct": correct_answers,
        "total": total_questions
    }

    save_results(USER_RESULTS)

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=f"Тест завершен!\nВы ответили правильно на {correct_answers} из {total_questions} вопросов."
    )

async def show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать прогресс пользователя."""
    user_id = str(update.effective_user.id)  # Убедитесь, что user_id - строка
    if user_id not in USER_RESULTS or not USER_RESULTS[user_id]:
        await update.message.reply_text("У вас пока нет записей о прогрессе.")
        return

    progress = USER_RESULTS[user_id]
    progress_text = "Ваш прогресс:\n"
    for test, result in progress.items():
        percentage = (result['correct'] / result['total']) * 100
        progress_text += f"{test}: {result['correct']} из {result['total']} правильно ({percentage:.2f}%)\n"

    await update.message.reply_text(progress_text)

def main():
    """Запустить бота."""
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_access_code))
    application.add_handler(CommandHandler("modules", show_modules))
    application.add_handler(CommandHandler("progress", show_progress))
    application.add_handler(CallbackQueryHandler(module_selected, pattern=r'^Модуль [0-9]+$'))
    application.add_handler(CallbackQueryHandler(lesson_selected, pattern=r'^Модуль [0-9]+:Урок [0-9]+$'))
    application.add_handler(CallbackQueryHandler(start_quiz, pattern=r'^quiz:.*$'))
    application.add_handler(CallbackQueryHandler(handle_quiz_answer, pattern=r'^answer:.*$'))

    application.run_polling()

if __name__ == "__main__":
    main()


# 7717768554:AAEm2Ynen2L0DCNbLGZ9xzT_7k9sfZXcwc4