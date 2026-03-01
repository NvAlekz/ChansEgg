# ChansEgg - PokeMMO Breeding Planner

ChansEgg is an external desktop tool for planning Pokemon breeding in PokeMMO with a visual node-based workflow, cost estimation, and inventory-aware optimization.

---

## ES - Que es ChansEgg

ChansEgg es una herramienta de escritorio externa para planificar crianza en PokeMMO.  
Su objetivo es reducir errores manuales y mostrar una ruta clara de breeding (IVs, naturaleza, genero y costos) antes de ejecutar cruces en el juego.

### ES - Funcionalidades principales

- Planificador visual por capas/nodos para objetivos `Nx31`.
- Soporte de naturaleza con Everstone dentro del flujo de crianza.
- Desglose de costos por brazales, genero, pokeballs y naturaleza.
- Plan de genero y notas operativas por capa.
- Ventana avanzada de informacion Pokemon:
  - Datos
  - Movimientos (nivel, huevo, TM, HM)
  - Estadisticas base
  - Sitios
  - Evoluciones
- Inventario tipo PC Box:
  - Grilla de slots por caja
  - Drag and drop entre slots
  - Edicion de datos del breeder (genero, naturaleza, IVs, nivel, notas, ball, precio)
  - Persistencia JSON en AppData
- Integracion inventario -> planner:
  - Asignacion automatica de nodos desde inventario
  - Etiquetas visuales `INV` y `BUY` en nodos
  - Desglose adicional de compras faltantes estimadas
- i18n completo de interfaz: Espanol, Ingles y Chino simplificado.
- Temas configurables (paletas + modo dark/light).
- Cache local de sprites e iconos con fallback robusto.
- Filtro de especies enfocado a disponibilidad de PokeMMO.
- Splash screen de inicio y updater en background con GitHub Releases.

### ES - Reglas de calculo (resumen funcional)

- El motor calcula padres base, cruces por capas y consumo de objetos por cruce.
- Brazales y Everstone se reflejan en nodos y costos.
- El plan de genero se calcula por capa para asegurar parejas viables.
- El inventario se evalua como recurso inicial para cubrir nodos requeridos.
- El costo final muestra:
  - Costo base de breeding
  - Faltantes estimados por inventario
  - Total combinado

---

## EN - What ChansEgg is

ChansEgg is an external desktop planner for PokeMMO breeding.  
It provides a clear pre-breeding route for IVs, nature, gender, and expected costs to reduce in-game mistakes.

### EN - Core features

- Node/layer breeding planner for `Nx31` goals.
- Nature workflow with Everstone handling.
- Detailed cost breakdown for braces, gender selection, pokeballs, and nature.
- Layered gender plan and operational notes.
- Advanced Pokemon info window:
  - Data
  - Moves (level, egg, TM, HM)
  - Base stats
  - Locations
  - Evolutions
- PC Box inventory module:
  - Slot grid per box
  - Drag and drop between slots
  - Breeder data editing (gender, nature, IVs, level, notes, ball, paid price)
  - JSON persistence in AppData
- Inventory-to-planner integration:
  - Automatic inventory assignment to required nodes
  - Visual `INV` / `BUY` node labels
  - Missing purchase estimate breakdown
- Full UI i18n: Spanish, English, Simplified Chinese.
- Theme system (palettes + dark/light mode).
- Local sprite/icon caching with robust fallbacks.
- PokeMMO-focused species filtering.
- Startup splash and background updater via GitHub Releases.

### EN - Calculation rules (functional overview)

- The engine computes base parents, layer-by-layer crosses, and item consumption.
- Braces and Everstone are reflected both visually and in costs.
- Gender requirements are planned per layer.
- Inventory is treated as available initial resources for node coverage.
- Final cost output combines:
  - Base breeding cost
  - Estimated missing purchases
  - Combined total

---

## Estructura del proyecto / Project structure

- `app.py`: main application (UI, planner, rendering, i18n wiring).
- `inventory.py`: inventory models, storage, matching, stats helpers.
- `launcher.py`: startup flow, splash, updater scheduling.
- `updater.py`: update check/download logic (GitHub Releases flow).
- `locales/`: UI translations (`es`, `en`, `zh`).
- `assets/`: local visual resources.
- `pokemmo_species.json`: species filtering source.
- `pokemon.json`: species base data used by the app.

---

## Solucion de problemas / Troubleshooting

- If sprites do not load, verify internet access and cache folder permissions.
- If themes look stale after switching, restart once and verify local config write permissions.
- If updater does not trigger, verify GitHub repo/user in updater config and release assets.
- If a Pokemon has partial info in the Info window, data may be limited by source endpoint/version mapping.

---

## Version

Current app version: **v1.0.1**

---

## License

See `LICENSE`.
