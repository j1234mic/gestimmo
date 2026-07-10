from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime

app = FastAPI(
    title="API Gestion Immobilière",
    description="API pour gestion de biens immobiliers",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Stockage en mémoire
properties = []
counter = 1

@app.get("/")
def root():
    return {"message": "API Immobilière", "docs": "/docs"}

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "version": "1.0.0"
    }

@app.get("/api/properties/")
def list_properties():
    return {"data": properties, "total": len(properties)}

@app.post("/api/properties/")
def create_property(property_data: dict):
    global counter
    property_data["id"] = counter
    property_data["reference"] = f"PROP-{counter:04d}"
    counter += 1
    properties.append(property_data)
    return property_data

@app.get("/api/properties/statistics")
def statistics():
    return {
        "total_properties": len(properties),
        "by_type": {},
        "by_status": {}
    }