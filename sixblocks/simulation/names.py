"""Name and label pools.

Names are drawn from a single mixed pool, independently of income, occupation, health or
any other attribute. Nothing about a resident's identity may be inferred from their name,
and nothing about their name may influence their behavior.
"""

from __future__ import annotations

FIRST_NAMES = [
    "Amara", "Nadia", "Priya", "Elena", "Rosa", "Yusuf", "Malik", "Diego", "Hana", "Ines",
    "Theo", "Mira", "Omar", "Lucia", "Ade", "Kai", "Sofia", "Jonas", "Leila", "Idris",
    "Marta", "Cyrus", "Noor", "Anton", "Bea", "Ravi", "Zora", "Felix", "Isha", "Bruno",
    "Talia", "Emeka", "Junko", "Pablo", "Sana", "Gil", "Vera", "Hugo", "Nia", "Arman",
    "Clara", "Tomas", "Ruth", "Selin", "Owen", "Yara", "Dov", "Anais", "Kwame", "Ilse",
    "Rami", "June", "Aleks", "Fatou", "Milo", "Dana", "Serge", "Nell", "Ozan", "Lupe",
]

LAST_NAMES = [
    "Okafor", "Rivera", "Novak", "Haddad", "Kim", "Delgado", "Mensah", "Petrov", "Aziz",
    "Moreau", "Serrano", "Bahri", "Lindqvist", "Osei", "Marchetti", "Salas", "Dvorak",
    "Ferreira", "Nakamura", "Bello", "Grady", "Vasquez", "Iyer", "Kowalski", "Amari",
    "Tran", "Bianchi", "Sowande", "Ruiz", "Halvorsen", "Farrell", "Duarte", "Bergman",
    "Adeyemi", "Costa", "Weiss", "Lozano", "Antic", "Barros", "Feng", "Rahman", "Oyelaran",
    "Sandoval", "Keller", "Mbeki", "Quintero", "Sato", "Varga", "Njoku", "Espinoza",
]

BLOCK_NAMES = {
    "block_a": "Marlow Row",
    "block_b": "Halden Square",
    "block_c": "Kestrel Heights",
    "block_d": "Ashgrove",
    "block_e": "Fenner Court",
    "block_f": "Sable End",
}

BUSINESS_NAME_PARTS = {
    "bodega": ["Corner", "Halden", "Sable", "Row", "Kestrel"],
    "grocery": ["Ashgrove", "Six Blocks", "Fenner"],
    "cafe": ["Slow", "Third Rail", "Morning", "Marlow"],
    "bakery": ["Kestrel", "Bright", "Early"],
    "restaurant": ["Marlow", "Halden", "Twelfth"],
    "pharmacy": ["Kestrel", "Neighborhood"],
    "laundromat": ["Fenner", "Sudsy", "Court"],
}

BUSINESS_NAME_SUFFIX = {
    "bodega": ["Deli & Grocery", "Market", "Bodega"],
    "grocery": ["Grocers", "Food Hall", "Market"],
    "cafe": ["Coffee", "Cafe", "Roasters"],
    "bakery": ["Bakery", "Bagels", "Bread"],
    "restaurant": ["Pizza", "Kitchen", "Diner"],
    "pharmacy": ["Pharmacy", "Drugs"],
    "laundromat": ["Laundromat", "Wash & Fold"],
}


def full_name(rng) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"


def business_name(rng, category: str) -> str:
    parts = BUSINESS_NAME_PARTS.get(category, ["Six Blocks"])
    suffix = BUSINESS_NAME_SUFFIX.get(category, ["Shop"])
    return f"{rng.choice(parts)} {rng.choice(suffix)}"
