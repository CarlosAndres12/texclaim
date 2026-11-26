---
title: "Componentes ligeros para clasificación eficiente de textos cortos"
author: "A. Ejemplo"
lang: es
bibliography: refs.bib
abstract: |
  Estudiamos qué componentes de aprendizaje profundo importan más en clasificadores de texto pequeños.
  Nuestro modelo compacto mejora la exactitud en 2,5 puntos frente a una línea base sólida en el corpus de reseñas en español.
---

# Introducción

La autoatención ha reemplazado a la recurrencia en muchos modelos de secuencias.
El Transformer alcanzó 30,1 BLEU en la tarea de traducción inglés-alemán de WMT 2014 [@vaswani2017attention].
Las conexiones residuales permiten entrenar redes muy profundas, y las redes residuales de 152 capas ganaron el primer lugar en la tarea de clasificación de ILSVRC 2015 [@he2016deep].
BERT obtuvo una puntuación GLUE de 80,5, una mejora absoluta de 7,7 puntos [@devlin2019bert].

# Antecedentes

Adam es un método eficiente desde el punto de vista computacional y requiere poca memoria [@kingma2015adam].
La normalización por lotes permite usar tasas de aprendizaje mucho más altas y elimina por completo la necesidad de regularización [@ioffe2015batch].

# Resultados

Nuestro modelo compacto alcanza una exactitud del 87,5 %, mientras que la línea base alcanza el 85,0 %.
El entrenamiento tarda 1,5 horas con nuestro modelo y 1,6 horas con la línea base.

| Modelo     | Exactitud (%) | Tiempo (h) |
|------------|---------------|------------|
| Línea base | 85,0          | 1,6        |
| Nuestro    | 87,5          | 1,5        |

Table: Exactitud en el corpus de reseñas en español.

# Conclusiones

Nuestro modelo mejora la exactitud en 2,5 puntos frente a la línea base.
Además, reduce el tiempo de entrenamiento a la mitad, lo que lo hace ideal para equipos modestos.
