# ============================================================================
# Laboratorio 02 - P1: Heap File con Registros de Longitud Fija
# Base de Datos II - UTEC
#
# Este archivo parte de "Fijo2.py" (ejemplo de clase: struct.pack/unpack +
# seek para acceso directo O(1) a registros de tamano fijo) y lo extiende
# agregando la capa de PAGINACION que pide el laboratorio:
#
#   FILE HEADER | PAGE 0 | PAGE 1 | ... | PAGE N-1
#
# Cada pagina tiene un PAGE HEADER + un arreglo de slots de tamano fijo.
# Cada registro se identifica con RID = (page_id, slot_id), y se soportan
# dos estrategias de eliminacion (vistas en la diapositiva "Registros de
# Longitud Fija: Eliminacion", Alternativas 2 y 3):
#
#   - MOVE THE LAST: al eliminar el slot i, se copia el ULTIMO registro
#     activo de la pagina hacia la posicion i, y se reduce el contador de
#     activos. No se deja "hueco": los slots activos siempre son
#     contiguos [0, num_active).
#
#   - FREE LIST: al eliminar el slot i, NO se mueve nada. El registro se
#     marca como eliminado y se reutiliza su propio espacio en disco para
#     guardar el "puntero" (indice) al siguiente slot libre. El page
#     header guarda la cabeza de esta lista enlazada (free_list_head).
#     Esto es exactamente el mecanismo "NextDel" mostrado en la diapositiva.
# ============================================================================

import struct
import os

# ----------------------------------------------------------------------------
# 1. FORMATO DEL REGISTRO "Alumno" (pedido por el enunciado del laboratorio)
# ----------------------------------------------------------------------------
# codigo(5s) + nombre(11s) + apellidos(20s) + carrera(15s) + ciclo(i) + mensualidad(d)
#
# Se agrega ademas un flag de estado (1 byte) al inicio del registro fisico:
#   activo = 1  -> registro valido
#   activo = 0  -> registro eliminado
#
# Para la estrategia FREE LIST, cuando un registro esta eliminado (activo=0)
# reutilizamos el campo entero "ciclo" (4 bytes) para guardar el slot_id del
# siguiente espacio libre (o -1 si es el final de la lista). Asi no gastamos
# bytes extra: el mismo espacio del registro muerto sirve como nodo de la
# lista enlazada (idea tomada directamente de la diapositiva "Free List").
RECORD_FORMAT = "B5s11s20s15sid"  # B=activo, 5s,11s,20s,15s=strings, i=ciclo, d=mensualidad
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)

# ----------------------------------------------------------------------------
# 2. FORMATO DEL FILE HEADER
# ----------------------------------------------------------------------------
# page_size(i) + num_pages(i)
FILE_HEADER_FORMAT = "ii"
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)

# ----------------------------------------------------------------------------
# 3. FORMATO DEL PAGE HEADER
# ----------------------------------------------------------------------------
# num_records(i)     -> slots totales usados alguna vez en la pagina (activos+eliminados)
# num_active(i)       -> registros activos (no eliminados) en la pagina
# free_list_head(i)   -> slot_id del primer espacio eliminado (-1 si no hay ninguno)
#
# num_records tambien funciona como "siguiente slot libre al final" para
# MOVE THE LAST (no hay huecos intermedios en ese modo, solo se crece al
# final o se reutiliza el ultimo).
PAGE_HEADER_FORMAT = "iii"
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)

# Tamano de pagina pequeno a proposito (el enunciado permite reducirlo)
# para poder forzar varias paginas con pocos registros de prueba.
PAGE_SIZE = 512

# Cuantos slots de registro caben en una pagina, dado el espacio que deja
# el page header.
SLOTS_PER_PAGE = (PAGE_SIZE - PAGE_HEADER_SIZE) // RECORD_SIZE


class Alumno:
    """Modelo de dominio (no incluye el flag 'activo', eso es un detalle
    de almacenamiento que solo maneja FixedRecord)."""

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
    """Identificador de registro: RID = (page_id, slot_id)."""

    def __init__(self, page_id, slot_id):
        self.page_id = page_id
        self.slot_id = slot_id

    def __repr__(self):
        return f"RID(page={self.page_id}, slot={self.slot_id})"

    def __eq__(self, other):
        return self.page_id == other.page_id and self.slot_id == other.slot_id


class FixedRecord:
    """
    Encapsula el manejo del Heap File de registros de longitud fija.

    mode: "MOVE_LAST" o "FREE_LIST" -> estrategia de eliminacion.

    Diseno del archivo:
        [FILE HEADER][PAGE 0 = PAGE HEADER + SLOTS][PAGE 1 = ...]...

    El acceso a un registro dado su RID=(page_id, slot_id) es O(1) porque
    se calcula el offset fisico directamente (misma idea de "offset = i *
    size" de la diapositiva, extendida con el nivel de pagina):

        offset = FILE_HEADER_SIZE
                 + page_id * PAGE_SIZE
                 + PAGE_HEADER_SIZE
                 + slot_id * RECORD_SIZE
    """

    def __init__(self, filename, mode="MOVE_LAST"):
        assert mode in ("MOVE_LAST", "FREE_LIST"), "modo invalido"
        self.filename = filename
        self.mode = mode

        # Si el archivo no existe (o esta vacio), lo inicializamos con
        # el File Header y cero paginas.
        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            with open(filename, "wb") as f:
                f.write(struct.pack(FILE_HEADER_FORMAT, PAGE_SIZE, 0))

    # ------------------------------------------------------------------
    # Utilidades internas de bajo nivel (offsets, lectura/escritura de
    # headers). Todas usan seek() para acceso directo, sin recorrer el
    # archivo secuencialmente.
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
        return self._page_offset(page_id) + PAGE_HEADER_SIZE + slot_id * RECORD_SIZE

    def _read_slot_raw(self, f, page_id, slot_id):
        """Devuelve la tupla cruda (activo, codigo, nombre, apellidos,
        carrera, ciclo_o_next, mensualidad) sin interpretar."""
        f.seek(self._slot_offset(page_id, slot_id))
        data = f.read(RECORD_SIZE)
        return struct.unpack(RECORD_FORMAT, data)

    def _write_slot_raw(self, f, page_id, slot_id, packed_bytes):
        f.seek(self._slot_offset(page_id, slot_id))
        f.write(packed_bytes)

    def _pack_alumno(self, alumno, activo=1):
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
        """Empaqueta un slot 'muerto' de la free list: activo=0 y el
        campo 'ciclo' reutilizado como puntero al siguiente libre.
        El resto de campos se deja en blanco/cero, ya no son validos."""
        return struct.pack(
            RECORD_FORMAT,
            0,
            b"\x00" * 5,
            b"\x00" * 11,
            b"\x00" * 20,
            b"\x00" * 15,
            next_free,
            0.0,
        )

    def _unpack_alumno(self, raw):
        # El flag 'activo' ya fue validado por el llamador (readRecord/load)
        # antes de invocar este metodo; aqui solo interesan los datos.
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
        """Agrega una pagina nueva al final del archivo, con su header
        inicializado (0 registros, 0 activos, free_list_head=-1) y crece
        el archivo hasta cubrir PAGE_SIZE bytes completos para esa pagina
        (asegura que los seeks posteriores no lean 'mas alla de EOF')."""
        page_id = num_pages
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, 0, 0, -1))
        f.write(b"\x00" * (PAGE_SIZE - PAGE_HEADER_SIZE))
        return page_id

    # ------------------------------------------------------------------
    # API publica pedida por el enunciado
    # ------------------------------------------------------------------

    def add(self, alumno):
        """
        Inserta un nuevo Alumno usando la estrategia de localizacion de
        paginas: recorre las paginas existentes buscando espacio libre
        segun el modo de eliminacion; si ninguna tiene espacio, crea una
        pagina nueva. Devuelve el RID asignado.

        - Modo FREE_LIST: una pagina "tiene espacio" si su free_list_head
          != -1 (hay un slot eliminado reutilizable) o si num_records <
          SLOTS_PER_PAGE (aun caben slots nuevos al final).
        - Modo MOVE_LAST: una pagina "tiene espacio" si num_active <
          SLOTS_PER_PAGE (los activos siempre son contiguos, sin huecos).
        """
        with open(self.filename, "r+b") as f:
            page_size, num_pages = self._read_file_header(f)

            target_page = None
            for page_id in range(num_pages):
                num_records, num_active, free_list_head = self._read_page_header(f, page_id)

                if self.mode == "FREE_LIST":
                    if free_list_head != -1 or num_records < SLOTS_PER_PAGE:
                        target_page = page_id
                        break
                else:  # MOVE_LAST
                    if num_active < SLOTS_PER_PAGE:
                        target_page = page_id
                        break

            # Ninguna pagina existente tiene espacio -> crear una nueva
            if target_page is None:
                target_page = self._new_page(f, num_pages)
                num_pages += 1
                self._write_file_header(f, page_size, num_pages)

            num_records, num_active, free_list_head = self._read_page_header(f, target_page)

            if self.mode == "FREE_LIST" and free_list_head != -1:
                # Reutilizar el primer espacio libre de la lista enlazada.
                slot_id = free_list_head
                _, _, _, _, _, next_free, _ = self._read_slot_raw(f, target_page, slot_id)
                new_free_list_head = next_free
                self._write_slot_raw(f, target_page, slot_id, self._pack_alumno(alumno))
                self._write_page_header(f, target_page, num_records, num_active + 1, new_free_list_head)
            else:
                # No hay libres reutilizables (o estamos en MOVE_LAST):
                # se agrega al final de los slots usados en la pagina.
                slot_id = num_records
                self._write_slot_raw(f, target_page, slot_id, self._pack_alumno(alumno))
                self._write_page_header(f, target_page, num_records + 1, num_active + 1, free_list_head)

            return RID(target_page, slot_id)

    def readRecord(self, rid):
        """Lee un registro directamente por (page_id, slot_id) -> O(1),
        sin recorrer el archivo. Devuelve None si el slot esta eliminado
        o el RID es invalido."""
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
                return None
            return self._unpack_alumno(raw)

    def remove(self, rid):
        """Elimina el registro identificado por rid, en O(1), aplicando
        la estrategia configurada en el constructor. Devuelve True si se
        elimino, False si el RID no correspondia a un registro activo."""
        with open(self.filename, "r+b") as f:
            _, num_pages = self._read_file_header(f)
            if rid.page_id < 0 or rid.page_id >= num_pages:
                return False

            num_records, num_active, free_list_head = self._read_page_header(f, rid.page_id)
            if rid.slot_id < 0 or rid.slot_id >= num_records:
                return False

            raw = self._read_slot_raw(f, rid.page_id, rid.slot_id)
            if raw[0] == 0:
                return False  # ya estaba eliminado

            if self.mode == "MOVE_LAST":
                # Alternativa 2 de la diapositiva: mover el ULTIMO
                # registro activo hacia la posicion eliminada, y reducir
                # en 1 el numero de activos (y de records, porque en
                # este modo no quedan huecos: los activos son siempre
                # [0, num_active)).
                last_slot = num_active - 1
                if rid.slot_id != last_slot:
                    last_raw = self._read_slot_raw(f, rid.page_id, last_slot)
                    self._write_slot_raw(
                        f, rid.page_id, rid.slot_id,
                        struct.pack(RECORD_FORMAT, *last_raw),
                    )
                # "Borramos" el ultimo slot (ya duplicado o ya era el
                # eliminado) dejandolo marcado como inactivo.
                self._write_slot_raw(f, rid.page_id, last_slot, self._pack_free_node(-1))
                self._write_page_header(f, rid.page_id, num_records - 1, num_active - 1, free_list_head)
            else:
                # Alternativa 3 (FREE LIST): no se mueve nada. El slot
                # eliminado pasa a ser la nueva cabeza de la lista de
                # libres, y guarda como "siguiente" el free_list_head
                # anterior (insercion al inicio de la lista, O(1)).
                self._write_slot_raw(f, rid.page_id, rid.slot_id, self._pack_free_node(free_list_head))
                self._write_page_header(f, rid.page_id, num_records, num_active - 1, rid.slot_id)

            return True

    def load(self):
        """Devuelve todos los registros validos (activos) del archivo,
        recorriendo pagina por pagina y slot por slot. A diferencia de
        readRecord/remove, esta operacion es intencionalmente O(n) ya
        que su proposito es un volcado completo, no un acceso puntual."""
        results = []
        with open(self.filename, "rb") as f:
            _, num_pages = self._read_file_header(f)
            for page_id in range(num_pages):
                num_records, _, _ = self._read_page_header(f, page_id)
                for slot_id in range(num_records):
                    raw = self._read_slot_raw(f, page_id, slot_id)
                    if raw[0] == 1:  # activo
                        results.append((RID(page_id, slot_id), self._unpack_alumno(raw)))
        return results

    # ------------------------------------------------------------------
    # Utilidad de depuracion para las pruebas funcionales (P1.py): imprime
    # el File Header y el Page Header de cada pagina.
    # ------------------------------------------------------------------
    def print_headers(self, titulo=""):
        with open(self.filename, "rb") as f:
            page_size, num_pages = self._read_file_header(f)
            print(f"--- {titulo} ---")
            print(f"FILE HEADER -> page_size={page_size}, num_pages={num_pages}")
            for page_id in range(num_pages):
                num_records, num_active, free_list_head = self._read_page_header(f, page_id)
                print(f"  PAGE {page_id} -> num_records={num_records}, "
                      f"num_active={num_active}, free_list_head={free_list_head}")
