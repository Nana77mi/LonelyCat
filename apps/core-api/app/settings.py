from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "LonelyCat Core API"
