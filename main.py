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
from flask import Flask, request

from db import DB

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

load_dotenv()
locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')

REQUIRED_ENV_VARS = ['RETAIL_URL', 'RETAIL_KEY', 'TG_TOKEN']
missing_vars = [var for var in REQUIRED_ENV_VARS if not os.getenv(var)]
if missing_vars:
    logger.error(f"Missing required environment variables: {', '.join(missing_vars)}")
    sys.exit(1)

client = retailcrm.v5(os.getenv('RETAIL_URL'), os.getenv('RETAIL_KEY'))

session = requests.Session()
retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
adapter = HTTPAdapter(max_retries=retry_strategy)
session.mount("http://", adapter)
session.mount("https://", adapter)

db = DB()
bot = telebot.TeleBot(os.getenv('TG_TOKEN'))

API_TIMEOUT = 10


def make_api_request(func, *args, **kwargs):
    """Wrapper for API requests with timeout and error handling"""
    try:
        kwargs['timeout'] = API_TIMEOUT
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"API request failed: {e}")
        raise


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
        button1 = telebot.types.InlineKeyboardButton(text='Получить список заказов', callback_data='get_orders')
        markup.add(button1)
        bot.send_message(chat_id=message.chat.id, text='Выберите действие:', reply_markup=markup)

        if need_delete_massage:
            bot.delete_message(message.chat.id, message.message_id)
    except Exception as e:
        logger.error(f"Error in send_menu: {e}")
        bot.send_message(message.chat.id, "Произошла ошибка. Попробуйте позже.")


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


def get_order_text(order):
    items_string = ''
    for item in order.get('items', []):
        item_name = item.get('offer', {}).get('displayName', '- Нет названия -')
        items_string += f" - {item_name}, {item['quantity']} шт.\n"

    order_text = f"\nСостав заказа:\n{items_string}\n"

    name_parts = ['lastName', 'firstName', 'patronymic']
    sender_name = ' '.join(filter(None, [order.get(part, '') for part in name_parts]))
    sender_phone = order.get('phone', {})

    order_text += f"Заказчик: <i>{sender_name}</i> <b>{sender_phone}</b>\n"

    recipient = order.get('customFields', {}).get('poluchatel', '')
    order_text += f"Получатель: <i>{recipient}</i>\n"

    delivery_date = order.get('delivery', {}).get('date', '?')
    order_text += f"\nДата доставки: <b>{delivery_date}</b>\n"

    delivery_time = order.get('delivery', {}).get('time', {})
    delivery_time_from = delivery_time.get('from', '?')
    delivery_time_to = delivery_time.get('to', '?')
    delivery_time = f"{delivery_time_from} - {delivery_time_to}"
    order_text += f"Время доставки: <b>{delivery_time}</b>\n"

    delivery_address = order.get('delivery', {}).get('address', {})
    delivery_address_fields = []
    if delivery_address.get('city', ''):
        delivery_address_fields.append(delivery_address['city'])
    if delivery_address.get('street', ''):
        if delivery_address.get('streetType', ''):
            delivery_address_fields.append(f"{delivery_address['streetType']} {delivery_address['street']}")
        else:
            delivery_address_fields.append(delivery_address['street'])
    if delivery_address.get('building', ''):
        delivery_address_fields.append(f"дом {delivery_address['building']}")
    if delivery_address.get('house', ''):
        delivery_address_fields.append(f"строение {delivery_address['house']}")
    if delivery_address.get('housing', ''):
        delivery_address_fields.append(f"корпус {delivery_address['housing']}")
    if delivery_address.get('block', ''):
        delivery_address_fields.append(f"подъезд {delivery_address['block']}")
    if delivery_address.get('floor', ''):
        delivery_address_fields.append(f"этаж {delivery_address['floor']}")
    if delivery_address.get('flat', ''):
        delivery_address_fields.append(f"квартира {delivery_address['flat']}")

    delivery_address_text = ', '.join(delivery_address_fields)
    if delivery_address_text == '':
        delivery_address_text = delivery_address.get('text', '')

    order_text += f"Адрес доставки: <i>{delivery_address_text}</i>\n"

    if delivery_address.get('notes', ''):
        order_text += f"\nКомментарий к адресу: <i>{delivery_address['notes']}</i>\n"

    customer_comment = order.get('customerComment', '')
    if customer_comment == '':
        customer_comment = ' - '
    order_text += f"Комментарий клиента: <i>{customer_comment}</i>\n"

    manager_comment = order.get('managerComment', '')
    if manager_comment == '':
        manager_comment = ' - '
    order_text += f"Комментарий менеджера: <i>{manager_comment}</i>\n"

    order_text += f"\nСтоимость: <b>{order['totalSumm']}</b>₽\n"

    try:
        payment_types = client.payment_types().get_response()['paymentTypes']
        payment_type_names = {}
        for payment_type_code, payment_type in payment_types.items():
            payment_type_names[payment_type['code']] = payment_type['name']

        for [payment_id, payment] in order.get('payments', []).items():
            payment_type = payment.get('type', '')
            order_text += f"Тип оплаты: <b>{payment_type_names.get(payment_type, 'Неизвестно')}</b>\n"
            paid_text = 'Оплачено' if payment.get('status', '') == 'paid' else 'Не оплачено'
            order_text += f"Статус оплаты: <b>{paid_text}</b>\n"
    except Exception as e:
        logger.error(f"Error fetching payment types: {e}")

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


@bot.callback_query_handler(lambda call: 'ORDER;' in call.data)
def order_info(call):
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

        order_text = f"Заказ: <b>{order['number']}</b>\n"
        order_text += get_order_text(order)

        markup = telebot.types.InlineKeyboardMarkup()
        button1 = telebot.types.InlineKeyboardButton(text='Назад', callback_data='get_orders')

        markup.add(button1)

        button2 = telebot.types.InlineKeyboardButton(
            text='Возврат',
            callback_data=f'ORDER_APPROVE;{order_id};CANCEL'
        )
        button3 = telebot.types.InlineKeyboardButton(
            text='Доставлен',
            callback_data=f'ORDER_APPROVE;{order_id};DELIVERY'
        )
        markup.add(button2, button3)

        order_photos = get_order_photos(order)

        if len(order_photos) > 0:
            first_photo = order_photos[0]
            bot.delete_message(call.message.chat.id, call.message.message_id)
            bot.send_photo(call.message.chat.id, first_photo, caption=order_text, parse_mode='HTML', reply_markup=markup)
        else:
            bot.edit_message_text(
                order_text,
                call.message.chat.id,
                call.message.message_id,
                parse_mode='HTML',
                reply_markup=markup
            )
    except Exception as e:
        logger.error(f"Error in order_info: {e}")
        bot.send_message(call.message.chat.id, "Ошибка при получении информации о заказе. Попробуйте позже.")
        send_menu(call.message)


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
            text_message = f"<b>Вы доставили заказ {order['number']}.</b>\n"
            text_message += get_order_text(order)
            order_photos = get_order_photos(order)
        elif command == 'CANCEL':
            new_status = 'vozvrat-im'
            text_message = f"Вы вернули заказ {order['number']}"
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


app = Flask(__name__)

WEBHOOK_HOST = os.getenv('RENDER_EXTERNAL_HOSTNAME')
WEBHOOK_PORT = int(os.getenv('PORT', 10000))
WEBHOOK_URL = f"https://{WEBHOOK_HOST}/{os.getenv('TG_TOKEN')}" if WEBHOOK_HOST else None

@app.route('/')
def index():
    return 'Bot is running!'

@app.route(f'/{os.getenv("TG_TOKEN")}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    else:
        return 'Error: Invalid content type', 403

def main():
    logger.info("Bot starting...")
    
    if WEBHOOK_HOST:
        logger.info(f"Setting up webhook at {WEBHOOK_URL}")
        try:
            # Remove webhook first
            bot.remove_webhook()
            time.sleep(2)
            bot.set_webhook(url=WEBHOOK_URL)
            logger.info("Webhook set up successfully")
        except Exception as e:
            logger.error(f"Webhook setup error: {e}")
        
        # Run Flask app
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
