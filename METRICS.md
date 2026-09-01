# Métricas del Dashboard

Toda cifra del dashboard es un conteo de filas, un conteo de hallazgos, o un
porcentaje derivado de esos dos. No hay estimaciones, ni conversiones a dinero,
ni constantes de ajuste.

## Vocabulario

Tres cantidades distintas que antes se mezclaban bajo la palabra "issues":

| Término | Definición | Cota |
| --- | --- | --- |
| **Hallazgo** (`findings` / `issue_count`) | Una combinación **regla + campo** que falló al menos una vez. `missing_value` sobre `address` y sobre `price` son dos hallazgos. | Sin cota respecto de las filas |
| **Violación** (`rule_violations`) | Una regla disparando sobre una fila. Una fila que rompe tres reglas aporta tres. | **Puede superar el total de filas** |
| **Fila afectada** (`rows_affected`) | Fila distinta que falló **al menos una** regla activa. | `0 ≤ rows_affected ≤ total_rows` |
| **Fila crítica** (`critical_rows`) | Fila distinta que falló al menos una regla de severidad **alta**. | `0 ≤ critical_rows ≤ rows_affected` |

> Un issue representa **una combinación regla + campo que falló**, no una fila.
> Rows affected representa **una fila distinta con al menos un problema**.

Ejemplo: 10 filas, 3 de ellas con `address` y `price` vacíos.

```
hallazgos        = 4    (missing_value/address, missing_value/price,
                         invalid_address, invalid_price)
violaciones      = 12   (4 reglas x 3 filas)
filas afectadas  = 3
filas críticas   = 3
```

El sistema anterior sumaba las 12 violaciones, las llamaba "filas" y las dividía
por 10 filas reales, produciendo un score de calidad de 0 sobre un dataset que
está 70% limpio.

## Fórmulas

```
quality_score = 100 × (1 − rows_affected / total_rows)
risk_score    = 100 × critical_rows / total_rows
```

Implementadas una sola vez en
[`compute_scores`](backend/app/services/quality_run.py).

**Quality score** — porcentaje de filas que pasaron todas las reglas activas.
Acotado a [0, 100] por construcción: `rows_affected` cuenta filas distintas y
nunca puede exceder `total_rows`. Vale 100 con datos limpios y 0 cuando todas
las filas fallan. Es inmune al doble conteo porque no suma violaciones.

**Risk score** — porcentaje de filas con al menos un problema de severidad alta.
Sin pesos ni factores: es literalmente una fracción del dataset, verificable
contra el CSV. Se muestra en el dashboard como *Filas críticas* (valor absoluto
más su porcentaje).

**Dataset vacío** — ambos valen 0, pero la API lo marca como no medido
(`datasets_measured`) para que la UI diga "Sin datos" en lugar de "0% de
calidad".

## Validación de esquema

Antes de ejecutar cualquier regla, el sistema verifica que el CSV pertenezca al
dominio seleccionado. Implementado en
[`check_schema`](backend/app/services/schema_check.py), a partir de los mismos
`DOMAIN_PROFILES` que usan las reglas.

| Estado | Cuándo | Reglas | Quality score |
| --- | --- | --- | --- |
| **compatible** | Todas las requeridas presentes, sin columnas ajenas ni tipos rotos | Se ejecutan | Se calcula |
| **warning** | Es el tipo de dato correcto pero falta alguna requerida, sobran columnas, o una columna tipada no parsea | Se ejecutan | Se calcula |
| **incompatible** | Falta `order_id`, **o** hay menos del 60% de las columnas requeridas | **No se ejecutan** | **`null`** |

**Por qué `null` y no 0%.** Un 0% afirma "todas las filas están mal", que es una
conclusión sobre la calidad de los datos. En un archivo de otro dominio esa
conclusión nunca se midió: lo único que se midió es que el archivo no
corresponde. Las columnas `quality_score`, `risk_score` y `rows_affected` de
`dataset_runs` ya eran nullable, así que el estado se representa sin plumbing
nuevo, y los agregados del dashboard (que exigen `rows_affected`) excluyen el
dataset en lugar de contarlo como limpio o como completamente roto.

Umbrales (política declarada en `schema_check.py`):

- `MIN_REQUIRED_COVERAGE = 0.6` — por debajo, las reglas medirían la ausencia de
  un esquema en lugar de la calidad de los datos.
- `MAX_INVALID_TYPE_RATIO = 0.5` — más de la mitad de los valores sin parsear
  significa que la columna no contiene lo que su nombre declara. Por debajo es
  suciedad de datos, y de eso ya se ocupan las reglas.
- `TYPE_SAMPLE_ROWS = 200` — misma muestra que el preview, costo O(1).

Los tipos esperados por columna están declarados en `FIELD_TYPES`
(`data_quality.py`), junto a los conjuntos categóricos que las reglas ya usaban.
Antes ese conocimiento estaba implícito en el cuerpo de cada regla.

## Reglas con definición revisada

**`invalid_address`** — una dirección debe contener **al menos una letra y al
menos un dígito** (nombre de calle + numeración), y solo se evalúa cuando no
está vacía.

Antes era `len(address) < 6`, que rechazaba direcciones legítimas cortas
("Av 9") mientras aceptaba incompletas ("Sarmiento", nueve caracteres y sin
número), y además disparaba sobre **toda** dirección vacía, duplicando la regla
`missing_value`/`address` que ya la reportaba. Medido sobre el dataset demo: las
mismas 54 filas se contaban dos veces.

**`order_id` vacío** — se reporta una sola vez, como `missing_value`/`order_id`.
El hallazgo `missing_order_id` reportaba la misma condición sobre las mismas
filas por segunda vez y fue eliminado. Las tres condiciones quedan separadas:

| condición | dónde se reporta |
| --- | --- |
| columna `order_id` ausente | Schema Validation → `incompatible` |
| `order_id` vacío | regla `missing_value`/`order_id`, severidad alta |
| `order_id` duplicado | regla `duplicate_order_id`, severidad alta |

Ninguno de los dos cambios movió `rows_affected`, `critical_rows`,
`quality_score` ni `risk_score`: esas métricas cuentan filas, no disparos.

## Severidad

Es una **política de negocio declarada**, no un número derivado. Vive en
[`severity_for`](backend/app/services/data_quality.py):

- **Alta** — `order_id`, `address` o `postal_code` faltantes; precio inválido;
  dirección inválida; inconsistencias de fecha de entrega; órdenes duplicadas.
  Bloquean el despacho.
- **Baja** — campos operativos opcionales faltantes.
- **Media** — todo lo demás.

## Detección de anomalías

```
z_modificado = (valor − mediana) / (1.4826 × MAD)      |z| ≥ 3.5  ⇒  anomalía
```

Implementado en [`run_anomaly_detection`](backend/app/services/data_quality.py).

**Qué busca.** Valores *legales pero implausibles*: un precio de 6.000 en un
catálogo que va de 10 a 500 no viola ninguna regla y casi seguro es un punto
decimal mal puesto. Los valores *imposibles* (precio negativo, stock negativo,
peso cero) **no** son anomalías: los rechaza el motor de reglas, y están a ~1.5
desviaciones robustas de la mediana — no son estadísticamente extremos.

**Por qué mediana y MAD, no media y σ.** La versión anterior calculaba media y
desvío poblacional **sobre la muestra contaminada**. Con outliers presentes, σ
se infla lo suficiente como para que los propios outliers queden dentro de su
umbral: el efecto de enmascaramiento. El MAD tiene punto de ruptura 50%, así que
apenas se mueve hasta que la mitad de los datos está contaminada. Medido sobre 5
seeds reservados:

| contaminación | recall con σ | recall con MAD | σ inflado |
| --- | --- | --- | --- |
| 1% | 0.800 | 0.808 | 2.9× |
| 5% | 0.604 | 0.809 | 5.6× |
| 10% | 0.417 | 0.818 | 7.5× |
| 20% | 0.114 | 0.804 | 9.3× |
| 30% | **0.000** | 0.809 | 8.9× |

**Umbral 3.5** es la recomendación publicada de Iglewicz y Hoaglin (1993) para
el z-score modificado. **No fue elegido optimizando sobre estos datos**: las
columnas sintéticas son uniformes y acotadas, de modo que el |z| máximo de un
valor normal es 1.46 y no existe ningún valor entre 1.46 y el outlier más
cercano. Cualquier umbral en esa brecha da precisión 1.000, así que el dataset
demo **no puede discriminar umbrales**. Elegir el que maximiza F1 aquí sería
ajustar sobre el conjunto de evaluación.

**Constantes**: 1.4826 hace del MAD un estimador insesgado de σ para datos
normales; 1.2533 hace lo mismo con la desviación absoluta media, usada solo
cuando el MAD colapsa a cero (más de la mitad de los valores idénticos). Una
columna constante se omite.

**Solapamiento con las reglas**: 18% de las faltas de regla numéricas también se
reportan como anomalía, porque algunas (lead time de 30 días, descuento de 85%)
son a la vez imposibles y extremas. Los dos conteos responden preguntas
distintas y **no deben sumarse**.

**Evaluación reproducible**: `python scripts/eval_anomalies.py`.

## Tendencia

```
delta_points = quality_actual − quality_anterior
```

Compara la **última corrida de cada dataset contra su corrida anterior**, leídas
de `dataset_runs`. Se expresa en **puntos porcentuales**, no en variación
porcentual: la calidad ya es un porcentaje, y un cociente entre dos porcentajes
no significa nada y además se rompe con denominador cero.

`quality_trend` es **`null`** cuando ningún dataset tiene dos corridas
comparables, y la UI no muestra nada en ese caso.

Antes se derivaba una "semana anterior" de `dataset.last_run_at`, un único
timestamp: un dataset solo puede caer en una de las dos ventanas, así que la
ventana anterior siempre quedaba vacía y **todos los deltas daban +100%**.

Las corridas grabadas antes de que existiera el conteo por filas tienen
`rows_affected = NULL` y se excluyen de la comparación en lugar de leerse
como cero.

## Métricas eliminadas

| Métrica | Motivo |
| --- | --- |
| **Impacto estimado (US$)** | Se calculaba como `violaciones_ponderadas × base(dominio) + anomalías × base × 0.4`, con `base` ∈ {120, 90, 110} — constantes sin origen ni unidad. El sistema no tiene ningún dato económico, así que no hay forma de calcular dinero. Reemplazado por *Filas afectadas*. |
| **Riesgo operativo (score 0–100)** | Mezclaba violaciones ponderadas con anomalías vía un factor 50 arbitrario, y llegaba a 100 sobre un dataset 70% limpio. Reemplazado por *Filas críticas*, que es un conteo. |
| **Deltas semanales (6 métricas)** | Estructuralmente siempre +100% o −100%. Reemplazados por una única tendencia de calidad basada en corridas reales. |

## Fuente de cada KPI

| KPI | Endpoint | Origen |
| --- | --- | --- |
| Calidad de datos | `GET /dashboard/kpis` → `quality_score` | `Σ rows_affected / Σ total_rows` sobre `datasets.quality_summary` |
| Filas afectadas | `rows_affected`, `rows_affected_pct` | idem |
| Filas críticas | `critical_rows`, `critical_rows_pct` | idem |
| Hallazgos | `findings` | `Σ issue_count` |
| Violaciones | `rule_violations` | `Σ rule_violations` |
| Anomalías | `anomalies` | `Σ anomaly_summary.anomaly_count` (el contador persistido, no la lista truncada a 50) |
| Casos abiertos | `open_cases` | `COUNT(cases WHERE status != 'resolved')`, misma definición que `/cases/summary` |
| Tendencia | `quality_trend` | `dataset_runs`, última vs. anterior por dataset |
| Calidad por dataset | `GET /dashboard/insights` → `dataset_health[].score` | misma fórmula de quality score |

## Tests

```bash
cd backend && python -m pytest tests/test_dashboard_metrics.py tests/test_schema_validation.py
```

`test_dashboard_metrics.py` (25): dataset limpio, con problemas, múltiples
reglas por fila, todo afectado, vacío, cotas del score, ausencia de baseline,
ausencia de campos monetarios, consistencia con `/cases/summary`, y una corrida
real de punta a punta.

`test_schema_validation.py` (26): esquema correcto, una y varias columnas
requeridas ausentes, columna inesperada, tipos incompatibles, CSV totalmente
ajeno, dataset válido con problemas de calidad, el incompatible que no ejecuta
reglas ni produce score, y el mismo archivo aceptado por un dominio y rechazado
por otro.
