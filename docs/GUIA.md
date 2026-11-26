# Guía de usuario de texclaim

texclaim verifica si las obras que cita respaldan lo que dice su manuscrito. También verifica sus
afirmaciones sin cita, el resumen y las conclusiones frente a sus propios resultados. Lee LaTeX,
Markdown y Word, y tiene una aplicación web en español e inglés. *English version:
[GUIDE.md](GUIDE.md).* Para agentes de IA: [../AGENTS.md](../AGENTS.md).

## 1. Abrir la aplicación web

```bash
texclaim serve --open          # http://127.0.0.1:8765
```

Todo lo de esta guía se hace desde la aplicación web. No hace falta editar archivos.

## 2. Conectar un modelo (página Configuración)

Abra **Configuración** en la barra superior. Hay tres opciones:

1. **Un agente de línea de comandos con sesión iniciada: sin clave de API.** Si Claude Code, pi o
   Antigravity está instalado en este computador, aparece en *Agentes de línea de comandos* con un
   botón **Probar**. Pulse **Usar por defecto**. Modelos: `cli:claude`, `cli:pi`, `cli:agy`;
   agregue `/modelo` para elegir uno, p. ej. `cli:claude/haiku`. Se cobran a su suscripción, por
   eso el costo aparece como 0 USD. Claude Code y pi se ejecutan sin ninguna herramienta, así que
   son la opción más segura.
2. **Una clave de API.** Pegue la clave en *Claves de API de proveedores de modelos*
   (Anthropic, OpenAI, Gemini, Mistral, DeepSeek, Groq, OpenRouter, Azure) y pulse **Guardar**, y
   luego **Probar**. Elija un modelo como `anthropic/claude-haiku-5-5` en *Modelo por defecto*.
   Funciona cualquier modelo de [LiteLLM](https://docs.litellm.ai/docs/providers); los modelos
   locales de Ollama (`ollama/qwen3`) no necesitan clave.
3. **Demo.** `demo` da veredictos ficticios para explorar la interfaz gratis.

Las claves se guardan en este computador en un archivo `.env` que solo usted puede leer. El
navegador nunca las recibe; la página solo muestra *Configurada* o *Sin configurar*.

**Fuentes (opcional).** Una clave de OpenAlex y una de Asta (Semantic Scholar) permiten encontrar
más textos completos con límites más altos. El correo de contacto lo identifica ante OpenAlex y
arXiv.

**Valores por defecto.** Idioma de las explicaciones, longitud de la afirmación y costo máximo por
ejecución. Cada proyecto puede cambiarlos.

## 3. Crear un proyecto

**Nuevo proyecto** → arrastre una carpeta, un `.zip` o archivos (`.tex` + `.bib`, `.md`, `.docx`,
y los PDF de las obras citadas si los tiene). También puede abrir una carpeta local en su lugar;
los informes se escriben junto a su manuscrito.

## 4. Configuración del proyecto

| Opción | Significado |
| --- | --- |
| Modelo | Reemplaza el modelo por defecto en este proyecto |
| Longitud de la afirmación | `auto` (el modelo decide qué cubre cada cita), 1 oración, 2 oraciones o el párrafo completo |
| Verificar afirmaciones sin cita y conclusiones | Las afirmaciones sin cita, el resumen y las conclusiones se comparan con sus propios resultados; elija secciones o deje todas sin marcar para todo el documento |
| Idioma de las explicaciones | Idioma de explicaciones e informes (auto sigue al manuscrito) |
| Costo máximo | La ejecución se detiene antes de superarlo |
| Sin conexión | Usa solo los PDF que usted dio y la caché |
| **Avanzado** | Evidencia (texto completo o pasajes), límites de tokens, verificaciones en paralelo, qué fuentes probar y en qué orden, límites de OpenAlex/arXiv, carpetas de PDF, macros de cita adicionales, cómo se eligen las afirmaciones sin cita |

Los cambios se guardan automáticamente.

## 5. Ejecutar y revisar

Pulse **Verificar ahora**. La pestaña *Ejecutar* muestra cada paso y cada veredicto en cuanto
llega. Luego:

- **Vista general**: veredictos de citas y afirmaciones internas, cobertura de fuentes, costo,
  descargas (informes HTML, Word, Markdown, JSON; todas las fuentes en `.zip`).
- **Hallazgos**: filtre y busque. Cada hallazgo muestra qué está mal, qué dice la fuente, una
  corrección sugerida y el PDF citado abierto en la página de la cita, con la cita resaltada.
- **Documento**: su manuscrito coloreado por veredicto.
- **Fuentes**: el estado de cada obra citada. Vea o descargue su PDF, o suba uno que falte.
- **Grafo**: un grafo de conocimiento de secciones, afirmaciones, obras citadas y las entidades
  que mencionan.

Las ejecuciones siguientes verifican solo lo que cambió. **Verificar todo de nuevo** pregunta
antes de reemplazar resultados.

## 6. Veredictos

| Veredicto | Significado |
| --- | --- |
| Respaldada | La fuente afirma o implica directamente lo dicho |
| Parcialmente respaldada | La idea central se sostiene, pero se exagera, redondea o amplía |
| Contradicha | La fuente (o sus propios resultados) dicen algo distinto |
| No encontrada | Se leyó toda la fuente y no trata la afirmación |
| No verificable | El texto disponible no permite decidir (sin PDF, solo resumen, una medición primaria) |

## 7. Equivalentes en línea de comandos

```bash
texclaim config show | set NOMBRE=VALOR | set NOMBRE_SECRETO | unset NOMBRE | test [--model M] [--openalex] [--asta]
texclaim check ARTICULO [--model M] [--claim-scope auto|sentence|two|paragraph] [--internal-section S] [--dry-run]
texclaim export ARTICULO --format html|docx
texclaim sources export ARTICULO
texclaim doctor
```

## 8. Privacidad

Las oraciones del manuscrito y los pasajes de las fuentes se envían al modelo que elija: un agente
de línea de comandos, la API de un proveedor o un modelo local de Ollama. Para trabajos
confidenciales use un modelo local.
