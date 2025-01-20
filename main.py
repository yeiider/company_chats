from fastapi import FastAPI, Body, Query,HTTPException,status
from datetime import datetime
import motor.motor_asyncio
from pydantic import BaseModel,Field
from typing import Optional
from typing import List


# -------------------------------------------------------------------
# 1. MODELOS (schemas con Pydantic)
# -------------------------------------------------------------------

class ChatListItem(BaseModel):  # MOVER ESTE MODELO AQUÍ ARRIBA
    chatId: str
    contactPhone: str
    displayName: Optional[str] = None
    updatedAt: Optional[str] = None

class CompanyCreate(BaseModel):
    companyId: str
    name: str
    alias: str
    phone: str

# Otras definiciones de clases como Company, Message, etc...
class Company(BaseModel):
    companyId: str
    name: str
    alias: Optional[str] = None
    phone: Optional[str] = None


class Message(BaseModel):
    messageId: str
    role: str
    body: str
    timestamp: int
    date: str
    status: Optional[str] = None
    type: Optional[str] = None
    ack: Optional[str] = None

class ContactInfo(BaseModel):
    displayName: Optional[str] = None
    phone: str

class Chat(BaseModel):
    companyId: str
    companyAlias: str
    companyPhone: str

    chatId: str
    contact: ContactInfo
    messages: List[Message] = Field(default_factory=list)

    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None



# -------------------------------------------------------------------
# 2. CONFIGURACIÓN FASTAPI & CONEXIÓN MONGO
# -------------------------------------------------------------------

app = FastAPI(title="Chat API", version="1.0.0")

# Conexión a Mongo (usa tu URI real, variables de entorno, etc.)
MONGO_URI = "mongodb://mongo:sRiKzeRoAjfGoQxdolJLJjGqTgrqttqJ@monorail.proxy.rlwy.net:15930"  # Ajusta tu conexión
client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
db = client["chatdb"]  # Nombre de tu base de datos
chats_collection = db["chats"]  # Nombre de la colección
companies_collection = db["companies"]


# -------------------------------------------------------------------
# 3. UTILIDADES
# -------------------------------------------------------------------

@app.post("/companies", response_model=CompanyCreate)
async def create_company(company_data: CompanyCreate):
    """
    Crea una nueva empresa en la colección `companies`.
    Retorna los datos de la empresa creada.
    """
    # Verifica si ya existe una empresa con el mismo companyId (opcional)
    existing = await companies_collection.find_one({"companyId": company_data.companyId})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A company with this companyId already exists."
        )

    # Inserta en Mongo
    new_company = company_data.dict()
    result = await companies_collection.insert_one(new_company)

    # Retornamos el objeto que se insertó (sin _id, o con _id si gustas)
    # En caso de querer retornar con _id, haz otra consulta para recuperarlo
    return company_data

@app.get("/companies", response_model=List[Company])
async def get_companies():
    """
    Devuelve el listado de todas las empresas registradas.
    """
    # Buscamos todas las empresas en la colección
    cursor = companies_collection.find({})
    results = await cursor.to_list(length=1000)  # límite arbitrario
    # Convertimos cada documento a un modelo `Company`.
    # Ojo: cada doc viene con _id, etc. Podrías mapearlo según tus necesidades
    companies = []
    for doc in results:
        # doc['_id'] es el ObjectId, que usualmente no incluyes en tu modelo
        companies.append(Company(
            companyId=doc.get("companyId", ""),
            name=doc.get("name", ""),
            alias=doc.get("alias"),
            phone=doc.get("phone")
        ))
    return companies

async def get_chat(company_id: str, contact_phone: str) -> dict:
    """
    Retorna el documento de un chat si existe.
    """
    chat = await chats_collection.find_one({
        "companyId": company_id,
        "chatId": contact_phone
    })
    return chat

# -------------------------------------------------------------------
# 4. ENDPOINT PARA GUARDAR (CREAR/ACTUALIZAR) EL CHAT
# -------------------------------------------------------------------
@app.post("/chats", response_model=Chat)
async def upsert_chat(data: Chat = Body(...)):
    """
    - Recibe la estructura de chat y/o mensajes desde n8n o desde tu webhook.
    - Hace upsert (buscar un chat existente o crearlo).
    - Inserta el nuevo mensaje en la lista de mensajes si corresponde.
    """

    # 1) Verificamos si ya existe un chat para esta companyId + contact.phone
    existing_chat = await get_chat(data.companyId, data.contact.phone)
    now_str = datetime.utcnow().isoformat()

    if existing_chat:
        # 2) Si ya existe el chat, "pusheamos" los mensajes nuevos en messages.
        #    En tu caso, podría llegar 1 mensaje nuevo, o varios.
        #    Suponiendo que en data.messages viene 1 o más mensajes.
        result = await chats_collection.update_one(
            {
                "_id": existing_chat["_id"]
            },
            {
                "$push": {
                    "messages": {
                        "$each": [m.dict() for m in data.messages]
                    }
                },
                "$set": {
                    "updatedAt": now_str
                }
            }
        )
        # Volvemos a leer el chat actualizado para retornarlo
        updated_chat = await chats_collection.find_one({"_id": existing_chat["_id"]})
        return Chat(**updated_chat)

    else:
        # 3) No existe el chat, lo creamos
        data.createdAt = now_str
        data.updatedAt = now_str
        new_chat = data.dict()
        insert_result = await chats_collection.insert_one(new_chat)
        created_chat = await chats_collection.find_one({"_id": insert_result.inserted_id})
        return Chat(**created_chat)


# -------------------------------------------------------------------
# 5. ENDPOINT PARA CONSULTAR UN CHAT
# -------------------------------------------------------------------
@app.get("/chats", response_model=Chat)
async def get_chat_by_company_and_contact(
    company_id: str = Query(..., alias="companyId"),
    contact_phone: str = Query(..., alias="contactPhone")
):
    """
    Permite consultar un chat dado un companyId y el teléfono del contacto.
    """
    chat = await get_chat(company_id, contact_phone)
    if chat:
        return Chat(**chat)
    return {"detail": "Chat not found."}

@app.get("/chats/list", response_model=List[ChatListItem])
async def get_chats_by_company(companyId: str):
    """
    Retorna un listado de chats (ID de chat, teléfono, nombre, updatedAt)
    para la empresa dada por companyId.
    """
    # Filtramos los chats por companyId
    cursor = chats_collection.find({"companyId": companyId})
    documents = await cursor.to_list(length=1000)

    # Armamos la lista con sólo la info necesaria
    chat_list = []
    for doc in documents:
        chat_list.append(ChatListItem(
            chatId=doc.get("chatId", ""),
            contactPhone=doc["contact"].get("phone", ""),
            displayName=doc["contact"].get("displayName"),
            updatedAt=doc.get("updatedAt")
        ))

    return chat_list


# -------------------------------------------------------------------
# 1. MODELOS (schemas con Pydantic)
# -------------------------------------------------------------------


# Resto de tu código sigue igual...


# -------------------------------------------------------------------
# 6. EJECUCIÓN
# -------------------------------------------------------------------
# Si deseas correr con: uvicorn main:app --reload
