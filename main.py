import locale
import os
import time
import sys
import retailcrm
import telebot
import requests
import logging

from dotenv import load_dotenv
from telebot.types import Message, KeyboardButton, ReplyKeyboardMarkup, CallbackQuery, InputMediaPhoto
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from flask import Flask, request, jsonify

from db import DB

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

load_dotenv()
locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')

# Initialize Flask app
app = Flask(__name__)

# Global variables (initialized later)
client = None
db = None
bot = None
API_TIMEOUT = 10

session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME')
WEBHOOK_PORT = int(os.getenv('PORT', 10000))
TG_TOKEN = os.getenv('TG_TOKEN')
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{TG_TOKEN}" if WEBHOOK_HOST and TG_TOKEN else None


def init_bot():
    """Initialize bot and client"""
    global client, db, bot
    
    logger.info("Initializing bot...")
    
    REQUIRED_ENV_VARS = ['RETAIL_URL', 'RETAIL_KEY', 'TG_TOKEN']
    missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
        return False
    
    try:
        client = retailcrm.v5(os.getenv('RETAIL_URL'), os.getenv('RETAIL_KEY'))
        db = DB()
        bot = telebot.TeleBot(os.getenv('TG_TOKEN'))
        
        # Register handlers
        register_handlers()
        
        logger.info("Bot initialized successfully")
        return True
    except Exception as e:
        logger.error(f"Failed to initialize bot: {e}")
        return False


def register_handlers():
    """Register all bot handlers"""
    
    @bot.message_handler(commands=['start'])
    def starter(message):
        keyboard = ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
        button_phone = KeyboardButton(
            text="Отправить телефон",
            request_contact=True,
        )
        keyboard.add(button_phone)
        bot.send_message(
            message.chat.id,
            'Отправьте свой телефон через меню в верхнем правом углу экрана, или нажав на кнопку ниже.',
            reply_markup=keyboard,
        )

    @bot.message_handler(commands=['menu'])
    def send_menu(message: Message, need_delete_massage=True):
        try:
            courier = db.get_courier_id(message.chat.id)
            if courier is None:
                starter(message)
                return

            markup = telebot.types.InlineKeyboardMarkup()
            button1 = telebot.types.InlineKeyboardButton(text='📋 Получить список заказов', callback_data='get_orders')
            button2 = telebot.types.InlineKeyboardButton(text='🏆 Мой рейтинг', callback_data='my_rating')
            markup.add(button1)
            markup.add(button2)
            bot.send_message(chat_id=message.chat.id, text='Выберите действие:', reply_markup=markup)

            if need_delete_massage:
                bot.delete_message(message.chat.id, message.message_id)
        except Exception as e:
            logger.error(f"Error in send_menu: {e}")

    @bot.message_handler(content_types=['contact'])
    def auth(message: Message):
        try:
            phone = message.contact.phone_number
            phone = ''.join(filter(str.isdigit, phone))

            answer = client.couriers().get_response()

            for courier in answer['couriers']:
                if not courier['active']:
                    continue

                courier_phones = courier.get('phone', {}).get('number', '')
                for courier_phone in courier_phones.split(','):
                    courier_phone = ''.join(filter(str.isdigit, courier_phone))
                    if phone != courier_phone:
                        continue

                    db.add_courier(message.chat.id, courier['id'])

                    name_parts = ['lastName', 'firstName', 'patronymic']
                    courier_full_name = ' '.join(filter(None, [courier.get(part, '') for part in name_parts]))

                    welcome_text = f'Здравствуйте, {courier_full_name}!'
                    bot.send_message(message.chat.id, welcome_text, reply_markup=telebot.types.ReplyKeyboardRemove())

                    send_menu(message)
                    return

            bot.send_message(
                chat_id=message.chat.id,
                text='Вы не зарегистрированы в системе, пожалуйста обратитесь к администратору и нажмите /start повторно'
            )
        except Exception as e:
            logger.error(f"Error in auth: {e}")
            bot.send_message(message.chat.id, "Ошибка авторизации. Попробуйте позже.")

    @bot.callback_query_handler(lambda call: 'menu' in call.data)
    def menu(call):
        send_menu(call.message)

    @bot.message_handler(commands=['rating'])
    def rating_command(message: Message):
        try:
            courier = db.get_courier_id(message.chat.id)
            if courier is None:
                starter(message)
                return
            
            show_rating(message.chat.id, courier)
        except Exception as e:
            logger.error(f"Error in rating command: {e}")

    def show_rating(chat_id, courier_id):
        """Show rating stats for a courier"""
        try:
            day_count = db.get_completed_orders_count(courier_id, 'day')
            week_count = db.get_completed_orders_count(courier_id, 'week')
            month_count = db.get_completed_orders_count(courier_id, 'month')
            
            # Get top couriers for each period
            top_day = db.get_top_couriers('day', 5)
            top_week = db.get_top_couriers('week', 5)
            top_month = db.get_top_couriers('month', 5)
            
            message = "🏆 <b>Ваш рейтинг</b>\n\n"
            message += f"📊 <b>Статистика доставок:</b>\n"
            message += f"  Сегодня: {day_count} заказов\n"
            message += f"  За неделю: {week_count} заказов\n"
            message += f"  За месяц: {month_count} заказов\n\n"
            
            # Find courier's position in daily top
            day_position = None
            for i, (cid, count) in enumerate(top_day, 1):
                if cid == courier_id:
                    day_position = i
                    break
            
            if day_position:
                message += f"⭐ <b>Ваша позиция:</b>\n"
                message += f"  За сегодня: #{day_position} место\n"
            else:
                message += "⭐ Продолжайте работать, чтобы попасть в топ!\n"
            
            markup = telebot.types.InlineKeyboardMarkup()
            button = telebot.types.InlineKeyboardButton(text='🏠 В меню', callback_data='menu')
            markup.add(button)
            
            bot.send_message(chat_id, message, parse_mode='HTML', reply_markup=markup)
        except Exception as e:
            logger.error(f"Error showing rating: {e}")

    @bot.callback_query_handler(lambda call: 'my_rating' in call.data)
    def my_rating_callback(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
            courier = db.get_courier_id(call.message.chat.id)
            if courier is None:
                starter(call.message)
                return
            
            show_rating(call.message.chat.id, courier)
        except Exception as e:
            logger.error(f"Error in my_rating callback: {e}")

    @bot.callback_query_handler(lambda call: 'get_orders' in call.data)
    def get_orders(call):
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)

            courier = db.get_courier_id(call.message.chat.id)
            if courier is None:
                starter(call.message)
                return

            day_orders = []
            limit = 100
            page = 1
            max_pages = 10

            while page <= max_pages:
                try:
                    answer = client.orders(
                        filters={
                            'extendedStatus': ['dostavliaet-kurer-ash', 'dostavliaet-kurer-iandeks'],
                            'deliveryTypes': ['yandex', 'kurer-ash'],
                            'couriers': [courier],
                        },
                        limit=limit,
                        page=page
                    ).get_response()
                    
                    for order in answer['orders']:
                        day_orders.append(order)

                    if len(answer['orders']) < limit:
                        break
                    page += 1
                except Exception as e:
                    logger.error(f"Error fetching orders page {page}: {e}")
                    break

            if not day_orders:
                bot.send_message(call.message.chat.id, f'Доставляемых вами заказов пока нет')
                send_menu(call.message)
                return

            markup = telebot.types.InlineKeyboardMarkup()
            for order in day_orders:
                order_number = order['number']

                delivery_date = order.get('delivery', {}).get('date', '?')

                delivery_time = order.get('delivery', {}).get('time', {})
                delivery_time_from = delivery_time.get('from', '?')
                delivery_time_to = delivery_time.get('to', '?')
                delivery_time = f"{delivery_time_from}-{delivery_time_to}"

                button = telebot.types.InlineKeyboardButton(
                    text=f"{order_number} ({delivery_date} {delivery_time})",
                    callback_data=f'ORDER;{order["id"]}'
                )
                markup.add(button)

            button = telebot.types.InlineKeyboardButton(text='Назад', callback_data='menu')
            markup.add(button)

            bot.send_message(call.message.chat.id, f'Собранные для вас заказы:', reply_markup=markup)
        except Exception as e:
            logger.error(f"Error in get_orders: {e}")
            bot.send_message(call.message.chat.id, "Ошибка при получении заказов. Попробуйте позже.")
            send_menu(call.message)

    @bot.callback_query_handler(lambda call: 'ORDER;' in call.data)
    def order_info(call):
        try:
            logger.info(f"order_info called with data: {call.data}")
            courier = db.get_courier_id(call.message.chat.id)
            if courier is None:
                logger.warning(f"No courier found for chat_id: {call.message.chat.id}")
                starter(call.message)
                return

            order_id = call.data.split(';')[1]
            logger.info(f"Fetching order {order_id} for courier {courier}")
            
            try:
                order = client.order(order_id, 'id').get_response()['order']
                logger.info(f"Order {order_id} fetched successfully")
            except Exception as e:
                logger.error(f"Error fetching order {order_id} from API: {e}")
                bot.send_message(call.message.chat.id, 'Не удалось получить информацию о заказе из системы. Попробуйте позже.')
                send_menu(call.message)
                return

            if order['delivery']['data']['courierId'] != courier:
                logger.warning(f"Order {order_id} courier mismatch: {order['delivery']['data']['courierId']} != {courier}")
                bot.send_message(call.message.chat.id, 'Что-то пошло не так, выберите заказ повторно:')
                send_menu(call.message)
                return

            if order['status'] not in ['dostavliaet-kurer-ash', 'dostavliaet-kurer-iandeks']:
                logger.warning(f"Order {order_id} has wrong status: {order['status']}")
                bot.send_message(call.message.chat.id, 'Статус заказа изменился, выберите заказ повторно:')
                send_menu(call.message)
                return

            try:
                order_text = f"Заказ: <b>{order['number']}</b>\n"
                order_text += get_order_text(order)
                logger.info(f"Order text generated for order {order_id}")
            except Exception as e:
                logger.error(f"Error generating order text for {order_id}: {e}")
                bot.send_message(call.message.chat.id, 'Ошибка при формировании информации о заказе. Попробуйте позже.')
                send_menu(call.message)
                return

            markup = telebot.types.InlineKeyboardMarkup()
            
            # Get customer phone for call button
            try:
                customer_phone = order.get('phone', '')
                if customer_phone:
                    # Clean phone number (remove all non-digit characters except +)
                    clean_phone = ''.join(c for c in str(customer_phone) if c.isdigit() or c == '+')
                    if clean_phone and not clean_phone.startswith('+'):
                        clean_phone = '+' + clean_phone
                    if clean_phone:
                        call_button = telebot.types.InlineKeyboardButton(
                            text='📞 Позвонить клиенту',
                            url=f'tel:{clean_phone}'
                        )
                        markup.add(call_button)
            except Exception as e:
                logger.error(f"Error creating call button for order {order_id}: {e}")
            
            button1 = telebot.types.InlineKeyboardButton(text='◀️ Назад', callback_data='get_orders')
            markup.add(button1)

            button2 = telebot.types.InlineKeyboardButton(
                text='↩️ Возврат',
                callback_data=f'ORDER_APPROVE;{order_id};CANCEL'
            )
            button3 = telebot.types.InlineKeyboardButton(
                text='✅ Доставлен',
                callback_data=f'ORDER_APPROVE;{order_id};DELIVERY'
            )
            markup.add(button2, button3)

            try:
                order_photos = get_order_photos(order)
                logger.info(f"Got {len(order_photos)} photos for order {order_id}")
            except Exception as e:
                logger.error(f"Error getting order photos for {order_id}: {e}")
                order_photos = []

            try:
                if len(order_photos) > 0:
                    first_photo = order_photos[0]
                    bot.delete_message(call.message.chat.id, call.message.message_id)
                    bot.send_photo(call.message.chat.id, first_photo, caption=order_text, parse_mode='HTML', reply_markup=markup)
                    logger.info(f"Order {order_id} info sent with photo")
                else:
                    bot.edit_message_text(
                        order_text,
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='HTML',
                        reply_markup=markup
                    )
                    logger.info(f"Order {order_id} info sent without photo")
            except Exception as e:
                logger.error(f"Error sending order info for {order_id}: {e}")
                # Try to send as new message if edit fails
                try:
                    bot.send_message(call.message.chat.id, order_text, parse_mode='HTML', reply_markup=markup)
                    logger.info(f"Order {order_id} info sent as new message")
                except Exception as e2:
                    logger.error(f"Failed to send order info as new message for {order_id}: {e2}")
                    bot.send_message(call.message.chat.id, "Ошибка при отображении заказа. Попробуйте получить список заказов снова.")
                    send_menu(call.message)
        except Exception as e:
            logger.error(f"Critical error in order_info: {e}")
            try:
                bot.send_message(call.message.chat.id, "Произошла ошибка. Попробуйте получить список заказов снова.")
                send_menu(call.message)
            except:
                pass

    @bot.callback_query_handler(lambda call: 'ORDER_APPROVE;' in call.data)
    def order_approve(call):
        try:
            courier = db.get_courier_id(call.message.chat.id)
            if courier is None:
                starter(call.message)
                return

            order_id = call.data.split(';')[1]

            order = client.order(order_id, 'id').get_response()['order']

            if order['delivery']['data']['courierId'] != courier:
                bot.send_message(call.message.chat.id, 'Что-то пошло не так, выберите заказ повторно:')
                send_menu(call.message)
                return

            if order['status'] not in ['dostavliaet-kurer-ash', 'dostavliaet-kurer-iandeks']:
                bot.send_message(call.message.chat.id, 'Что-то пошло не так, выберите заказ повторно:')
                send_menu(call.message)
                return

            command = call.data.split(';')[2]

            new_status = '-'
            order_photos = []
            text_message = ''

            if command == 'DELIVERY':
                new_status = 'zakaz-dostavlen'
                
                # Track completed order
                db.add_completed_order(courier, order_id, order['number'])
                
                # Get motivational phrase
                motivational = db.get_random_motivational_phrase()
                
                # Get personal stats
                day_count = db.get_completed_orders_count(courier, 'day')
                week_count = db.get_completed_orders_count(courier, 'week')
                month_count = db.get_completed_orders_count(courier, 'month')
                
                text_message = f"<b>✅ Заказ {order['number']} доставлен!</b>\n\n"
                text_message += f"🎉 {motivational}\n\n"
                text_message += f"📊 <b>Ваша статистика:</b>\n"
                text_message += f"  За сегодня: {day_count} заказов\n"
                text_message += f"  За неделю: {week_count} заказов\n"
                text_message += f"  За месяц: {month_count} заказов\n\n"
                text_message += get_order_text(order)
                order_photos = get_order_photos(order)
            elif command == 'CANCEL':
                new_status = 'vozvrat-im'
                text_message = f"❌ Вы вернули заказ {order['number']}"
                order_photos = []

            client.order_edit(
                {
                    'id': order['id'],
                    'status': new_status,
                },
                'id',
                order['site']
            )

            if order_photos:
                media = [InputMediaPhoto(photo) for photo in order_photos]
                media[0].caption = text_message
                media[0].parse_mode = 'HTML'
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.send_media_group(call.message.chat.id, media)
            else:
                bot.delete_message(call.message.chat.id, call.message.message_id)
                bot.send_message(call.message.chat.id, text_message, parse_mode='HTML')
            send_menu(call.message, need_delete_massage=False)
        except Exception as e:
            logger.error(f"Error in order_approve: {e}")
            bot.send_message(call.message.chat.id, "Ошибка при обработке заказа. Попробуйте позже.")
            send_menu(call.message)


def get_order_text(order):
    try:
        items_string = ''
        for item in order.get('items', []):
            try:
                item_name = item.get('offer', {}).get('displayName', '- Нет названия -')
                quantity = item.get('quantity', 1)
                items_string += f" - {item_name}, {quantity} шт.\n"
            except Exception as e:
                logger.error(f"Error processing order item: {e}")
                items_string += " - (ошибка загрузки товара)\n"

        order_text = f"\nСостав заказа:\n{items_string}\n"

        # Sender info with safe access
        try:
            name_parts = ['lastName', 'firstName', 'patronymic']
            sender_name = ' '.join(filter(None, [order.get(part, '') for part in name_parts]))
            sender_phone = order.get('phone', 'не указан')
            order_text += f"Заказчик: <i>{sender_name}</i> <b>{sender_phone}</b>\n"
        except Exception as e:
            logger.error(f"Error getting sender info: {e}")
            order_text += "Заказчик: (информация недоступна)\n"

        # Recipient
        try:
            recipient = order.get('customFields', {}).get('poluchatel', '')
            if recipient:
                order_text += f"Получатель: <i>{recipient}</i>\n"
        except Exception as e:
            logger.error(f"Error getting recipient: {e}")

        # Delivery date and time
        try:
            delivery_date = order.get('delivery', {}).get('date', '?')
            order_text += f"\nДата доставки: <b>{delivery_date}</b>\n"

            delivery_time = order.get('delivery', {}).get('time', {})
            delivery_time_from = delivery_time.get('from', '?')
            delivery_time_to = delivery_time.get('to', '?')
            delivery_time_str = f"{delivery_time_from} - {delivery_time_to}"
            order_text += f"Время доставки: <b>{delivery_time_str}</b>\n"
        except Exception as e:
            logger.error(f"Error getting delivery time: {e}")
            order_text += "\nИнформация о доставке недоступна\n"

        # Delivery address
        try:
            delivery_address = order.get('delivery', {}).get('address', {})
            delivery_address_fields = []
            
            fields_mapping = [
                ('city', None),
                ('street', 'streetType'),
                ('building', 'дом'),
                ('house', 'строение'),
                ('housing', 'корпус'),
                ('block', 'подъезд'),
                ('floor', 'этаж'),
                ('flat', 'квартира')
            ]
            
            for field, prefix in fields_mapping:
                value = delivery_address.get(field, '')
                if value:
                    if field == 'street' and delivery_address.get('streetType'):
                        delivery_address_fields.append(f"{delivery_address['streetType']} {value}")
                    elif prefix:
                        delivery_address_fields.append(f"{prefix} {value}")
                    else:
                        delivery_address_fields.append(value)
            
            delivery_address_text = ', '.join(delivery_address_fields)
            if not delivery_address_text:
                delivery_address_text = delivery_address.get('text', 'Адрес не указан')
            
            order_text += f"Адрес доставки: <i>{delivery_address_text}</i>\n"

            if delivery_address.get('notes'):
                order_text += f"\nКомментарий к адресу: <i>{delivery_address['notes']}</i>\n"
        except Exception as e:
            logger.error(f"Error getting delivery address: {e}")
            order_text += "Адрес доставки: (информация недоступна)\n"

        # Comments
        try:
            customer_comment = order.get('customerComment', '')
            if not customer_comment:
                customer_comment = ' - '
            order_text += f"Комментарий клиента: <i>{customer_comment}</i>\n"
        except Exception as e:
            logger.error(f"Error getting customer comment: {e}")

        try:
            manager_comment = order.get('managerComment', '')
            if not manager_comment:
                manager_comment = ' - '
            order_text += f"Комментарий менеджера: <i>{manager_comment}</i>\n"
        except Exception as e:
            logger.error(f"Error getting manager comment: {e}")

        # Total cost
        try:
            total_summ = order.get('totalSumm', 0)
            order_text += f"\nСтоимость: <b>{total_summ}</b>₽\n"
        except Exception as e:
            logger.error(f"Error getting total sum: {e}")

        # Payment info
        try:
            payment_types = client.payment_types().get_response()['paymentTypes']
            payment_type_names = {}
            for payment_type_code, payment_type in payment_types.items():
                payment_type_names[payment_type['code']] = payment_type['name']

            payments = order.get('payments', {})
            if payments:
                for payment_id, payment in payments.items():
                    payment_type = payment.get('type', '')
                    order_text += f"Тип оплаты: <b>{payment_type_names.get(payment_type, 'Неизвестно')}</b>\n"
                    paid_text = 'Оплачено' if payment.get('status', '') == 'paid' else 'Не оплачено'
                    order_text += f"Статус оплаты: <b>{paid_text}</b>\n"
        except Exception as e:
            logger.error(f"Error fetching payment types: {e}")
        
        return order_text
    except Exception as e:
        logger.error(f"Critical error in get_order_text: {e}")
        return "\n(Не удалось загрузить полную информацию о заказе)\n"

    return order_text


def get_order_photos(order):
    result_photo_urls = []

    offer_ids = []
    for item in order.get('items', []):
        offer_id = item.get('offer', {}).get('id', '')
        if offer_id and offer_id not in offer_ids:
            offer_ids.append(offer_id)

    if len(offer_ids) == 0:
        return result_photo_urls

    try:
        offers = client.products({'offerIds': offer_ids})

        for offer in offers.get_response()['products']:
            photo_url = offer.get('imageUrl', '')
            if photo_url:
                result_photo_urls.append(photo_url)
    except Exception as e:
        logger.error(f"Error fetching order photos: {e}")

    return result_photo_urls


@app.route('/')
def index():
    return 'Bot is running!'


@app.route('/health')
def health():
    """Health check endpoint to keep service awake"""
    return jsonify({'status': 'ok', 'service': 'bot-kurier'})


@app.route('/<path:token>', methods=['POST'])
def webhook(token):
    logger.info(f"Webhook received request for token: {token[:10]}...")
    
    if token != TG_TOKEN:
        logger.error("Invalid token")
        return 'Invalid token', 403
    
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        logger.info(f"Webhook data: {json_string[:200]}...")
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        logger.info("Webhook processed successfully")
        return ''
    else:
        logger.error(f"Invalid content type: {request.headers.get('content-type')}")
        return 'Error: Invalid content type', 403


def main():
    logger.info("Bot starting...")
    logger.info(f"WEBHOOK_HOST: {WEBHOOK_HOST}")
    logger.info(f"WEBHOOK_PORT: {WEBHOOK_PORT}")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL}")
    
    # Initialize bot
    if not init_bot():
        logger.error("Failed to initialize bot. Exiting.")
        sys.exit(1)
    
    if WEBHOOK_HOST:
        logger.info(f"Setting up webhook at {WEBHOOK_URL}")
        try:
            # Remove webhook first
            bot.remove_webhook()
            time.sleep(2)
            result = bot.set_webhook(url=WEBHOOK_URL)
            logger.info(f"Webhook set up result: {result}")
            
            # Verify webhook
            webhook_info = bot.get_webhook_info()
            logger.info(f"Webhook info: {webhook_info}")
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")
        
        # Run Flask app
        logger.info(f"Starting Flask server on port {WEBHOOK_PORT}")
        app.run(host='0.0.0.0', port=WEBHOOK_PORT)
    else:
        logger.info("No RENDER_EXTERNAL_HOSTNAME set, using polling mode")
        while True:
            try:
                logger.info("Starting polling...")
                bot.polling(
                    none_stop=True,
                    interval=1,
                    timeout=30,
                    long_polling_timeout=30
                )
            except Exception as e:
                logger.error(f"Polling error: {e}")
                logger.info("Restarting in 5 seconds...")
                time.sleep(5)


if __name__ == "__main__":
    main()
