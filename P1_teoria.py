# ============================================================================
# P1 - VERSION TEORIA / EXPLICADA
# Heap File con registros de LONGITUD FIJA (clase FixedRecord)
#
# Este archivo es funcionalmente identico a P1.py. La unica diferencia es que
# aqui se explica, paso a paso, el "por que" de cada decision de diseno,
# conectandolo con lo visto en la diapositiva "Registros, Paginacion y
# Organizacion de Archivos" (Semana 02) y con los requisitos del enunciado
# del Laboratorio 02.
# ============================================================================

import struct
import os

# ----------------------------------------------------------------------------
# POR QUE struct y no texto plano / pickle:
# El enunciado exige "archivo binario organizado en paginas de tamano fijo"
# con acceso O(1) por RID. Un archivo de texto obliga a recorrer registro por
# registro (delimitador \n) para saber donde empieza el i-esimo registro:
# eso es la Tecnica 1 de la diapositiva ("Archivos de Texto"), con el
# problema explicito de "Acceso directo a un registro: O(n)". Con struct
# empaquetamos cada registro a un tamano EXACTO y constante en bytes, lo que
# permite calcular su posicion fisica con una simple multiplicacion
# (offset = base + i * size), tal como muestra la diapositiva "Registros de
# Longitud Fija: Acceso Directo".
#
# POR QUE el formato "B5s11s20s15sid":
#   B  -> "activo": 1 byte (0/1). Flag de eliminacion logica (ver mas abajo).
#   5s, 11s, 20s, 15s -> codigo, nombre, apellidos, carrera: exactamente los
#         tamanos que pide el enunciado (Cadena[5], Cadena[11], Cadena[20],
#         Cadena[15]). Al ser "s" de tamano fijo, el campo SIEMPRE ocupa esos
#         bytes (con padding si el valor es mas corto) — asi se cumple el
#         requisito "Todos los registros en un archivo tienen la misma
#         longitud" de la diapositiva de Registros de Longitud Fija.
#   i  -> ciclo: entero (4 bytes), tal como pide el enunciado ("Entero").
#   d  -> mensualidad: double (8 bytes), para "Decimal" con precision real
#         (float de 4 bytes pierde precision para dinero, se prefiere double).
# ----------------------------------------------------------------------------
RECORD_FORMAT = "B5s11s20s15sid"
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)  # 64 bytes, fijo para TODOS los registros

# ----------------------------------------------------------------------------
# FILE HEADER: el enunciado exige como minimo (page_size, num_pages).
# page_size se guarda para que el archivo sea auto-descriptivo (no depende de
# una constante externa para poder leerse), y num_pages le dice a cada
# operacion cuantas paginas recorrer/en que rango son validos los page_id.
# ----------------------------------------------------------------------------
FILE_HEADER_FORMAT = "ii"
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)  # 8 bytes

# ----------------------------------------------------------------------------
# PAGE HEADER: el enunciado pide explicitamente que cada pagina tenga:
#   - numero total de registros en la pagina       -> num_records
#   - numero de registros activos (no eliminados)   -> num_active
#   - puntero al primer espacio eliminado (FREE_LIST) -> free_list_head
#
# POR QUE num_records Y num_active por separado (y no solo uno):
#   - num_records es el "alto de marca de agua" del slot array: hasta donde
#     hay slots FISICAMENTE escritos en la pagina (para MOVE_LAST, saber
#     cual es el "ultimo" registro a mover).
#   - num_active es cuantos de esos slots estan realmente vivos ahora mismo
#     (para saber si cabe un registro mas sin crear pagina nueva, y para
#     que load() no tenga que leer cada slot si se quisiera optimizar).
#   Con MOVE_LAST ambos siempre coinciden (nunca hay "huecos" en medio: el
#   ultimo activo se mueve a rellenar el hueco). Con FREE_LIST divergen:
#   num_records no baja al eliminar (el slot sigue "ocupando" espacio fisico
#   como tombstone), pero num_active si baja.
#
# free_list_head = -1 significa "no hay espacios libres" (lista vacia).
# Se eligio -1 y no 0 porque 0 es un slot_id valido.
# ----------------------------------------------------------------------------
PAGE_HEADER_FORMAT = "iii"
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)  # 12 bytes

# ----------------------------------------------------------------------------
# POR QUE PAGE_SIZE=512 y no 4096:
# El enunciado dice textualmente "PAGE_SIZE = 4096 bytes (para este
# laboratorio considerar un tamano mas pequeno)". Con 4096 bytes y registros
# de 64 bytes cabrian ~63 registros por pagina, y para forzar la creacion de
# "varias paginas" (requisito de las pruebas) con solo 100 registros de
# prueba se necesitarian pocas paginas, lo que no ejercita bien el codigo de
# "crear pagina nueva". Con 512 bytes se obtienen SLOTS_PER_PAGE=7, entonces
# 100 registros generan ~15 paginas: fuerza multiples creaciones de pagina y
# hace mucho mas facil verificar visualmente (via print_headers) el
# comportamiento pagina por pagina.
# ----------------------------------------------------------------------------
PAGE_SIZE = 512

SLOTS_PER_PAGE = (PAGE_SIZE - PAGE_HEADER_SIZE) // RECORD_SIZE  # (512-12)//64 = 7


class Alumno:
    """Estructura de datos pedida por el enunciado (registro logico, no el
    formato binario). Se mantiene separada de los bytes empaquetados para que
    el resto del programa trabaje con objetos Python normales."""

    def __init__(self, codigo, nombre, apellidos, carrera, ciclo, mensualidad):
        self.codigo = codigo
        self.nombre = nombre
        self.apellidos = apellidos
        self.carrera = carrera
        self.ciclo = ciclo
        self.mensualidad = mensualidad

    def __repr__(self):
        return (f"Alumno({self.codigo!r}, {self.nombre!r}, {self.apellidos!r}, "
                f"{self.carrera!r}, ciclo={self.ciclo}, mensualidad={self.mensualidad:.2f})")


class RID:
    """RID = (page_id, slot_id), tal como lo define el enunciado:
    "Cada registro debera identificarse mediante: RID = (page_id, slot_id)".
    Es el "puntero logico" que permite acceso O(1): dado un RID, no hace
    falta buscar nada, se calcula directamente el offset en el archivo."""

    def __init__(self, page_id, slot_id):
        self.page_id = page_id
        self.slot_id = slot_id

    def __repr__(self):
        return f"RID(page={self.page_id}, slot={self.slot_id})"

    def __eq__(self, other):
        return self.page_id == other.page_id and self.slot_id == other.slot_id


class FixedRecord:
    # ------------------------------------------------------------------
    # POR QUE un solo constructor con parametro "mode" en vez de dos clases:
    # El enunciado ofrece ambas opciones ("Puede separar la implementacion
    # en dos clases, una para cada modo"). Se eligio un solo modo
    # parametrizado porque MOVE_LAST y FREE_LIST comparten el 90% de la
    # logica (File Header, Page Header, pack/unpack de Alumno, calculo de
    # offsets); solo difieren en (a) como se localiza un slot libre en add()
    # y (b) que se hace con el slot vacante en remove(). Duplicar la clase
    # hubiera significado duplicar tambien ese 90% comun -> mas superficie
    # para bugs de sincronizacion entre las dos copias.
    # ------------------------------------------------------------------
    def __init__(self, filename, mode="MOVE_LAST"):
        assert mode in ("MOVE_LAST", "FREE_LIST"), "modo invalido"
        self.filename = filename
        self.mode = mode

        # Si el archivo no existe o esta vacio, se inicializa con un File
        # Header valido (num_pages=0) para que las demas operaciones no
        # tengan que manejar el caso "archivo recien creado" como especial.
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            with open(filename, "wb") as f:
                f.write(struct.pack(FILE_HEADER_FORMAT, PAGE_SIZE, 0))

    # ------------------------------------------------------------------
    # Helpers de bajo nivel: cada uno hace UNA sola cosa (leer/escribir un
    # header o un slot). Esto es lo que permite que add/readRecord/remove
    # sean O(1): nunca escanean el archivo, solo calculan un offset y hacen
    # un unico seek() + read()/write().
    # ------------------------------------------------------------------
    def _read_file_header(self, f):
        f.seek(0)
        data = f.read(FILE_HEADER_SIZE)
        page_size, num_pages = struct.unpack(FILE_HEADER_FORMAT, data)
        return page_size, num_pages

    def _write_file_header(self, f, page_size, num_pages):
        f.seek(0)
        f.write(struct.pack(FILE_HEADER_FORMAT, page_size, num_pages))

    def _page_offset(self, page_id):
        # Estructura del archivo pedida por el enunciado:
        # [FILE HEADER][PAGE 0][PAGE 1]...
        # Por eso el offset de una pagina es el tamano del File Header mas
        # page_id paginas completas (todas del mismo tamano fijo PAGE_SIZE).
        return FILE_HEADER_SIZE + page_id * PAGE_SIZE

    def _read_page_header(self, f, page_id):
        f.seek(self._page_offset(page_id))
        data = f.read(PAGE_HEADER_SIZE)
        num_records, num_active, free_list_head = struct.unpack(PAGE_HEADER_FORMAT, data)
        return num_records, num_active, free_list_head

    def _write_page_header(self, f, page_id, num_records, num_active, free_list_head):
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, num_records, num_active, free_list_head))

    def _slot_offset(self, page_id, slot_id):
        # Dentro de una pagina: [PAGE HEADER][slot 0][slot 1]...[slot k]
        # slot_id * RECORD_SIZE funciona SOLO porque todos los registros
        # tienen el mismo tamano (RECORD_SIZE) — la premisa central de
        # "Registros de Longitud Fija" en la diapositiva.
        return self._page_offset(page_id) + PAGE_HEADER_SIZE + slot_id * RECORD_SIZE

    def _read_slot_raw(self, f, page_id, slot_id):
        f.seek(self._slot_offset(page_id, slot_id))
        data = f.read(RECORD_SIZE)
        return struct.unpack(RECORD_FORMAT, data)

    def _write_slot_raw(self, f, page_id, slot_id, packed_bytes):
        f.seek(self._slot_offset(page_id, slot_id))
        f.write(packed_bytes)

    def _pack_alumno(self, alumno, activo=1):
        # POR QUE el flag "activo" en cada registro (ademas de num_active en
        # el header): permite a readRecord() detectar en O(1) si el registro
        # de ESE slot puntual esta vivo o muerto, sin tener que comparar su
        # slot_id contra num_active de la pagina (lo cual ademas NO
        # funcionaria en modo FREE_LIST, donde puede haber tombstones en
        # medio del rango [0, num_records)).
        return struct.pack(
            RECORD_FORMAT,
            activo,
            alumno.codigo.encode().ljust(5)[:5],
            alumno.nombre.encode().ljust(11)[:11],
            alumno.apellidos.encode().ljust(20)[:20],
            alumno.carrera.encode().ljust(15)[:15],
            alumno.ciclo,
            alumno.mensualidad,
        )

    def _pack_free_node(self, next_free):
        # ------------------------------------------------------------------
        # Esto es la implementacion literal de la "Alternativa 3" de la
        # diapositiva (Free List): "No mover registros, pero enlazar todos
        # los registros liberados en una lista", con la optimizacion que la
        # misma diapositiva sugiere: "Usar los mismos registros eliminados
        # para almacenar punteros". En vez de agregar un campo nuevo
        # "NextDel" (como en el ejemplo de la slide), REUTILIZAMOS el campo
        # entero existente "ciclo" para guardar next_free -- el registro ya
        # no tiene datos validos (activo=0), asi que ese espacio de 4 bytes
        # esta libre para usarse como puntero. Asi no se cambia el formato
        # binario del registro para soportar free list.
        # ------------------------------------------------------------------
        return struct.pack(
            RECORD_FORMAT,
            0,                  # activo = 0 -> tombstone
            b"\x00" * 5,
            b"\x00" * 11,
            b"\x00" * 20,
            b"\x00" * 15,
            next_free,          # reutiliza el slot "ciclo" como puntero next_free
            0.0,
        )

    def _unpack_alumno(self, raw):
        # "_activo" no se usa aqui porque el llamador (readRecord/load) ya
        # filtro por activo==1 antes de invocar unpack; se destructura con
        # guion bajo por convencion de Python para variables intencionalmente
        # descartadas (evita el warning de "no accedida" sin ocultar el dato).
        _activo, codigo, nombre, apellidos, carrera, ciclo, mensualidad = raw
        return Alumno(
            codigo.decode(errors="ignore").strip("\x00").strip(),
            nombre.decode(errors="ignore").strip("\x00").strip(),
            apellidos.decode(errors="ignore").strip("\x00").strip(),
            carrera.decode(errors="ignore").strip("\x00").strip(),
            ciclo,
            mensualidad,
        )

    def _new_page(self, f, num_pages):
        # free_list_head=-1 en una pagina recien creada: no hay ningun slot
        # eliminado todavia (lista de libres vacia).
        # Se escribe la pagina COMPLETA con ceros de una sola vez (en vez de
        # ir slot por slot) para dejar el archivo con el tamano final
        # correcto desde el principio y evitar tener que hacer seeks mas
        # alla del EOF despues.
        page_id = num_pages
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, 0, 0, -1))
        f.write(b"\x00" * (PAGE_SIZE - PAGE_HEADER_SIZE))
        return page_id

    def add(self, alumno):
        # ------------------------------------------------------------------
        # ESTRATEGIA DE LOCALIZACION DE PAGINA CON ESPACIO (pedida por el
        # enunciado como parte de add()): se recorren las paginas EXISTENTES
        # en orden y se usa la PRIMERA que tenga espacio (first-fit). No es
        # O(1) en el peor caso (podria recorrer todas las paginas si estan
        # llenas), pero es la estrategia mas simple posible y el enunciado
        # NO exige O(1) para add() (a diferencia de readRecord/remove que si
        # lo exigen explicitamente). Una alternativa mas rapida seria
        # guardar en el File Header un puntero a "ultima pagina con espacio"
        # -- se dejo fuera por ser complejidad extra no pedida (el enunciado
        # dice que es "opcional": "el estudiante podra agregar informacion
        # que facilite la localizacion de paginas con espacio disponible").
        #
        # La condicion de "tiene espacio" DEPENDE DEL MODO:
        #   - FREE_LIST: una pagina sirve si tiene un free_list_head valido
        #     (hay un tombstone para reciclar) O si aun no se llenaron todos
        #     los slots fisicos (num_records < SLOTS_PER_PAGE).
        #   - MOVE_LAST: una pagina sirve si num_active < SLOTS_PER_PAGE,
        #     porque en este modo num_records == num_active siempre (no
        #     quedan huecos), asi que solo importa cuantos activos hay.
        # ------------------------------------------------------------------
        with open(self.filename, "r+b") as f:
            page_size, num_pages = self._read_file_header(f)

            target_page = None
            for page_id in range(num_pages):
                num_records, num_active, free_list_head = self._read_page_header(f, page_id)

                if self.mode == "FREE_LIST":
                    if free_list_head != -1 or num_records < SLOTS_PER_PAGE:
                        target_page = page_id
                        break
                else:
                    if num_active < SLOTS_PER_PAGE:
                        target_page = page_id
                        break

            if target_page is None:
                # Ninguna pagina existente tiene espacio: crear una nueva.
                # Esto es exactamente el requisito de prueba "Verificar la
                # creacion de nuevas paginas cuando no exista espacio
                # disponible".
                target_page = self._new_page(f, num_pages)
                num_pages += 1
                self._write_file_header(f, page_size, num_pages)

            num_records, num_active, free_list_head = self._read_page_header(f, target_page)

            if self.mode == "FREE_LIST" and free_list_head != -1:
                # ------------------------------------------------------
                # Reusar un slot liberado en vez de usar uno nuevo.
                # free_list_head apunta al slot muerto MAS RECIENTEMENTE
                # eliminado (insercion al frente de la lista = LIFO), por
                # lo que el orden de reutilizacion natural de este diseno
                # es LIFO -- se verifica explicitamente en las pruebas.
                # ------------------------------------------------------
                slot_id = free_list_head
                # Se lee el nodo muerto para extraer el puntero al SIGUIENTE
                # libre (guardado en el campo "ciclo", ver _pack_free_node).
                _, _, _, _, _, next_free, _ = self._read_slot_raw(f, target_page, slot_id)
                new_free_list_head = next_free
                self._write_slot_raw(f, target_page, slot_id, self._pack_alumno(alumno))
                self._write_page_header(f, target_page, num_records, num_active + 1, new_free_list_head)
            else:
                # No hay nada que reciclar (o estamos en MOVE_LAST): se usa
                # el siguiente slot fisico libre al final de los ya usados.
                slot_id = num_records
                self._write_slot_raw(f, target_page, slot_id, self._pack_alumno(alumno))
                self._write_page_header(f, target_page, num_records + 1, num_active + 1, free_list_head)

            return RID(target_page, slot_id)

    def readRecord(self, rid):
        # ------------------------------------------------------------------
        # O(1) real: NO hay ningun bucle sobre registros. Se valida el rango
        # de page_id/slot_id (con los contadores del header, tambien O(1)) y
        # luego se hace un UNICO seek()+read() al offset exacto calculado por
        # _slot_offset(). Esto es lo que el enunciado exige explicitamente:
        # "obtiene el registro utilizando (page_id, slot_id) sin recorrer
        # secuencialmente todo el archivo con O(1)".
        # ------------------------------------------------------------------
        with open(self.filename, "rb") as f:
            _, num_pages = self._read_file_header(f)
            if rid.page_id < 0 or rid.page_id >= num_pages:
                return None

            num_records, _, _ = self._read_page_header(f, rid.page_id)
            if rid.slot_id < 0 or rid.slot_id >= num_records:
                return None

            raw = self._read_slot_raw(f, rid.page_id, rid.slot_id)
            activo = raw[0]
            if activo == 0:
                # El slot existe fisicamente pero es un tombstone: para el
                # usuario del Heap File, ese registro "no existe".
                return None
            return self._unpack_alumno(raw)

    def remove(self, rid):
        # ------------------------------------------------------------------
        # Tambien O(1): validar rango con los headers, leer el slot objetivo,
        # y aplicar la estrategia de eliminacion segun self.mode. Ninguna de
        # las dos ramas recorre otros registros aparte del propio slot (y,
        # en MOVE_LAST, del ultimo slot activo de la MISMA pagina).
        # ------------------------------------------------------------------
        with open(self.filename, "r+b") as f:
            _, num_pages = self._read_file_header(f)
            if rid.page_id < 0 or rid.page_id >= num_pages:
                return False

            num_records, num_active, free_list_head = self._read_page_header(f, rid.page_id)
            if rid.slot_id < 0 or rid.slot_id >= num_records:
                return False

            raw = self._read_slot_raw(f, rid.page_id, rid.slot_id)
            if raw[0] == 0:
                # Ya estaba eliminado: no es un error, pero no hay nada que
                # hacer -> se informa con False (evita doble-liberacion, que
                # en FREE_LIST podria corromper la lista enlazada).
                return False

            if self.mode == "MOVE_LAST":
                # --------------------------------------------------------
                # ALTERNATIVA 2 de la diapositiva ("Mover el registro n
                # hacia i"): el ultimo registro ACTIVO de la pagina se
                # mueve a la posicion que quedo vacante, y esa ultima
                # posicion se limpia. Esto MANTIENE a los activos siempre
                # contiguos en [0, num_active) -- por eso en este modo
                # num_records y num_active siempre coinciden.
                # --------------------------------------------------------
                last_slot = num_active - 1
                if rid.slot_id != last_slot:
                    last_raw = self._read_slot_raw(f, rid.page_id, last_slot)
                    self._write_slot_raw(
                        f, rid.page_id, rid.slot_id,
                        struct.pack(RECORD_FORMAT, *last_raw),
                    )
                # Si el registro eliminado YA era el ultimo, no hace falta
                # copiar nada (if de arriba se salta), solo limpiar su slot.
                self._write_slot_raw(f, rid.page_id, last_slot, self._pack_free_node(-1))
                self._write_page_header(f, rid.page_id, num_records - 1, num_active - 1, free_list_head)
            else:
                # --------------------------------------------------------
                # ALTERNATIVA 3 (Free List): NO se mueve nada. El slot
                # eliminado se convierte en un nodo de la lista enlazada de
                # libres, apuntando al que antes era el head (insercion al
                # frente -> LIFO), y el head de la pagina pasa a ser este
                # slot recien liberado.
                # num_records NO cambia (el slot sigue "existiendo"
                # fisicamente como tombstone dentro del rango escaneable),
                # solo baja num_active.
                # --------------------------------------------------------
                self._write_slot_raw(f, rid.page_id, rid.slot_id, self._pack_free_node(free_list_head))
                self._write_page_header(f, rid.page_id, num_records, num_active - 1, rid.slot_id)

            return True

    def load(self):
        # ------------------------------------------------------------------
        # Este es el UNICO metodo intencionalmente O(n): el enunciado pide
        # "load(): devuelve todos los registros validos del archivo", que
        # por definicion requiere tocar cada registro al menos una vez. No
        # contradice el requisito de O(1) de readRecord/remove, que son
        # operaciones puntuales por RID.
        # ------------------------------------------------------------------
        results = []
        with open(self.filename, "rb") as f:
            _, num_pages = self._read_file_header(f)
            for page_id in range(num_pages):
                num_records, _, _ = self._read_page_header(f, page_id)
                for slot_id in range(num_records):
                    raw = self._read_slot_raw(f, page_id, slot_id)
                    if raw[0] == 1:
                        results.append((RID(page_id, slot_id), self._unpack_alumno(raw)))
        return results

    def print_headers(self, titulo=""):
        # Utilidad de depuracion/evidencia: el enunciado pide explicitamente
        # "Mostrar el estado de los headers antes y despues de las
        # operaciones" como parte de las pruebas funcionales.
        with open(self.filename, "rb") as f:
            page_size, num_pages = self._read_file_header(f)
            print(f"--- {titulo} ---")
            print(f"FILE HEADER -> page_size={page_size}, num_pages={num_pages}")
            for page_id in range(num_pages):
                num_records, num_active, free_list_head = self._read_page_header(f, page_id)
                print(f"  PAGE {page_id} -> num_records={num_records}, "
                      f"num_active={num_active}, free_list_head={free_list_head}")
