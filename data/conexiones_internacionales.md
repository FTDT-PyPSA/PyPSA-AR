# Conexiones Internacionales en PSS/E

Interconexiones de Argentina con países vecinos presentes en el archivo `ver2526pid.raw`.

Relevante para cuando se modelen flujos de importación/exportación o se incorporen niveles de tensión inferiores al 500 kV.

---

## Tabla de interconexiones

| País | Bus ARG | Nombre ARG | kV | Bus Ext | Nombre Externo | Estado |
|------|---------|------------|----|---------|----------------|--------|
| Bolivia | 8337 | LIM ARG-BOL1 | 132 | 12000 | Equiv. ENDE | Activa |
| Bolivia | 8338 | LIM ARG-BOL2 | 132 | 12000 | Equiv. ENDE | Activa |
| Brasil | 86 | IBT F1 2345 | 345 | 87 | INF B1 | Activa ~3.060 MW export |
| Brasil | 5219 | URUGUAYANA | 132 | — | Red BR/RS | Activa |
| Chile | 8120 | COBOS | 345 | 8122 | ALTIPLANO | Activa 201 km |
| Chile | 8130 | LA PUNA | 345 | 19021 | — | Fuera de servicio |
| Chile | 8131 | CAU345 | 345 | — | Nodo interno | Activa (interno) |
| Paraguay | 5000 | YACYRETA | 500 | — | Generac. binac. | Activa |
| Paraguay | 5011 | ITAYPU | 500 | — | Equiv. Itaipu | Fuera de servicio |
| Paraguay | 5100 | CLORINDA | 220 | 5102 | CLOR-GUA | Fuera de servicio |
| Uruguay | 4208 | C.URUGUA1 | 132 | — | Salto Grande | Activa |
| Uruguay | 4221 | C.URUGUA2 | 132 | — | Salto Grande | Activa |
| Uruguay | 4225 | R_URUGUA | 132 | — | Salto Grande | Activa |
| Uruguay | 4347 | URUG_SUR | 132 | — | Salto Grande | Activa |

---

## Notas

- Las conexiones a 500 kV (YACYRETA, ITAYPU) ya están contempladas en el modelo 500 kV.
  YACYRETA está activa. ITAYPU está fuera de servicio en este snapshot.
- Las conexiones a 132, 220 y 345 kV se incorporarán cuando se construyan esos niveles de tensión.
- Los buses externos (Brasil, Bolivia, Chile) tienen `is_international = True` en `buses_500kv_raw.csv`
  y fueron excluidos del modelo 500 kV por `EXCLUDE_INTERNATIONAL = True` en el script 01.
