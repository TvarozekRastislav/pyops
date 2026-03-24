"""Inventory management REST API."""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

app = FastAPI(title="Inventory API", version="1.0.0")


class Item(BaseModel):
    name: str
    quantity: int
    price: float


class ItemUpdate(BaseModel):
    name: str | None = None
    quantity: int | None = None
    price: float | None = None


# In-memory storage
_inventory: dict[int, dict] = {}
_next_id: int = 1


@app.get("/health")
def health_check():
    return {"status": "healthy"}


@app.get("/items")
def list_items():
    return {"items": [{"id": k, **v} for k, v in _inventory.items()]}


@app.get("/items/{item_id}")
def get_item(item_id: int):
    if item_id not in _inventory:
        raise HTTPException(status_code=404, detail="Item not found")
    return {"id": item_id, **_inventory[item_id]}


@app.post("/items", status_code=201)
def create_item(item: Item):
    global _next_id
    _inventory[_next_id] = item.model_dump()
    result = {"id": _next_id, **_inventory[_next_id]}
    _next_id += 1
    return result


@app.put("/items/{item_id}")
def update_item(item_id: int, update: ItemUpdate):
    if item_id not in _inventory:
        raise HTTPException(status_code=404, detail="Item not found")
    current = _inventory[item_id]
    update_data = update.model_dump(exclude_unset=True)
    current.update(update_data)
    return {"id": item_id, **current}


@app.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int):
    if item_id not in _inventory:
        raise HTTPException(status_code=404, detail="Item not found")
    del _inventory[item_id]


@app.get("/stats")
def inventory_stats():
    if not _inventory:
        return {"total_items": 0, "total_value": 0.0, "avg_price": 0.0}
    total_qty = sum(v["quantity"] for v in _inventory.values())
    total_val = sum(v["quantity"] * v["price"] for v in _inventory.values())
    avg_price = sum(v["price"] for v in _inventory.values()) / len(_inventory)
    return {
        "total_items": total_qty,
        "total_value": round(total_val, 2),
        "avg_price": round(avg_price, 2),
        "unique_products": len(_inventory),
    }
