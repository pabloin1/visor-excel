"""Genera dos versiones de un Excel de prueba en muestras/v1 y muestras/v2 (mismo nombre)."""
import random
from pathlib import Path

import pandas as pd

random.seed(1)
productos = ["Café", "Té", "Pan dulce", "Galleta", "Jugo"]
zonas = ["Norte", "Sur", "Centro"]


def ventas(filas, mes):
    df = pd.DataFrame({
        "Fecha": pd.date_range(f"2026-{mes:02d}-01", periods=filas, freq="6h"),
        "Producto": [random.choice(productos) for _ in range(filas)],
        "Zona": [random.choice(zonas) for _ in range(filas)],
        "Cantidad": [random.randint(1, 20) for _ in range(filas)],
        "Precio": [round(random.uniform(15, 90), 2) for _ in range(filas)],
    })
    df["Total"] = (df["Cantidad"] * df["Precio"]).round(2)
    return df


for carpeta, mes, filas in [("v1", 9, 300), ("v2", 10, 450)]:
    out = Path("muestras") / carpeta
    out.mkdir(parents=True, exist_ok=True)
    df = ventas(filas, mes)
    resumen = df.groupby("Producto", as_index=False)[["Cantidad", "Total"]].sum()
    with pd.ExcelWriter(out / "ventas.xlsx") as w:
        df.to_excel(w, sheet_name="Ventas", index=False)
        resumen.to_excel(w, sheet_name="Resumen", index=False)
print("Listo: muestras/v1/ventas.xlsx y muestras/v2/ventas.xlsx")
