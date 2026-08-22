# ============================================================================
# P2 - VERSION TEORIA / EXPLICADA
# Heap File con registros de LONGITUD VARIABLE usando SlottedPage
#
# Este archivo es funcionalmente identico a P2.py. La unica diferencia es que
# aqui se explica, paso a paso, el "por que" de cada decision de diseno,
# conectandolo con lo visto en la diapositiva "Registros, Paginacion y
# Organizacion de Archivos" (Semana 02, seccion "Registros de Longitud
# Variable: Tecnicas") y con los requisitos del enunciado del Laboratorio 02
# (seccion "P2: Registros de Longitud Variable").
# ============================================================================

import struct
import os

# ----------------------------------------------------------------------------
# POR QUE Slotted Page y no "indicadores de longitud" a secas (Tecnica 2):
# La diapositiva presenta tres tecnicas para longitud variable: (1) archivos
# de texto con delimitador, (2) indicadores de longitud al inicio de cada
# campo, (3) Slotted Page. El enunciado EXIGE la (3): "Usar SlottedPage
# strategy para manejar registros de longitud variable dentro de cada
# pagina". La diferencia clave frente a (2) es que Slotted Page agrega un
# NIVEL DE INDIRECCION (el Slot Directory / ItemId Array): el RID no apunta
# directo a los bytes del registro, apunta a una ENTRADA en el directorio
# que a su vez guarda (offset, length). Esto es lo que permite mover o
# reorganizar los bytes de un registro (p.ej. en compact()) SIN cambiar el
# RID que el resto del sistema ya conoce -- tal como dice la diapositiva:
# "Permite compactar sin cambiar el RID externo".
#
# Dentro del registro Matricula SI se usa la Tecnica 2 (indicadores de
# longitud) para los dos campos de tamano variable (codigo, observaciones):
# cada uno se antecede de un entero con su longitud en bytes. Ambas tecnicas
# no son excluyentes: Slotted Page resuelve "donde esta cada registro dentro
# de la pagina", indicadores de longitud resuelven "donde termina cada campo
# dentro del registro".
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# POR QUE el prefijo "<" en TODOS los struct.pack/unpack de este archivo:
# Sin prefijo, Python usa "native byte order, native size, native alignment",
# lo que significa que el interprete puede INSERTAR BYTES DE RELLENO (padding)
# entre campos para alinearlos a fronteras de memoria (p.ej. un double de 8
# bytes se alinea a un multiplo de 8). Eso es invisible y no importa cuando
# se hace un UNICO pack()/unpack() con el mismo formato fijo de punta a
# punta (como en P1, donde RECORD_FORMAT nunca cambia).
#
# Pero en P2 los offsets DENTRO de un registro se calculan A MANO en
# _unpack_matricula (offset += len(codigo_b), offset += struct.calcsize("id"),
# etc.), porque el tamano de cada registro varia segun el contenido. Si el
# padding nativo variara segun la longitud de los strings empaquetados (y de
# hecho varia), esos offsets calculados a mano dejarian de coincidir con la
# posicion real de los bytes -> lectura corrupta. Esto NO es hipotetico: se
# encontro en la practica durante el desarrollo (struct.error: "unpack_from
# requires a buffer of at least ~289MB" al leer basura interpretada como
# longitud de string). El prefijo "<" (little-endian, SIN padding de
# alineacion) elimina el problema de raiz: el tamano empaquetado es siempre
# exactamente la suma de los tamanos de cada campo, sin sorpresas.
# ----------------------------------------------------------------------------

FILE_HEADER_FORMAT = "<ii"
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)

# ----------------------------------------------------------------------------
# PAGE HEADER pedido por el enunciado para SlottedPage:
#   "Numero de slots utilizados"        -> num_slots
#   "Puntero al espacio libre"          -> free_space_ptr
#   "Directory de slots / ItemId Array" -> (se modela como un array aparte,
#                                            ver SLOT_FORMAT mas abajo)
#
# POR QUE num_slots cuenta TAMBIEN los tombstones (slots eliminados):
# Si al eliminar se decrementara num_slots, el slot_id de un RID ya emitido
# podria dejar de ser valido para el rango [0, num_slots) aunque el dato
# siga fisicamente en la pagina esperando compactacion -- eso rompe la
# invariante "un RID emitido sigue siendo un identificador estable" que pide
# el enunciado. Por eso num_slots solo CRECE (nunca baja); un slot eliminado
# se queda contando pero con length=-1 (tombstone), igual a como el demo del
# PDF de clase muestra p.delete(1) seguido de p.read(1) devolviendo vacio,
# sin que el numero de slots de la pagina cambie.
#
# POR QUE free_space_ptr y no "free space size" directo:
# La diapositiva de Slotted Page indica que "las tuplas se insertan desde el
# final de la pagina hacia el inicio" y usa un "End of free space pointer".
# Guardar el PUNTERO (offset absoluto dentro de la pagina donde empieza la
# zona ya ocupada por datos) permite calcular en O(1) tanto (a) donde
# escribir el proximo registro (record_offset = free_space_ptr - len(raw))
# como (b) cuanto espacio libre queda (free_space_ptr - fin_del_slot_dir).
# ----------------------------------------------------------------------------
PAGE_HEADER_FORMAT = "<ii"
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)

# ----------------------------------------------------------------------------
# Slot Directory / ItemId Array: el enunciado lo describe literalmente como
# "array de pares (offset, length) para cada registro". length = -1 marca un
# slot eliminado (tombstone) -- se eligio -1 porque una longitud real nunca
# puede ser negativa, es un valor "imposible" que sirve de sentinela sin
# necesitar un flag booleano aparte (el mismo truco que free_list_head=-1 en
# P1 para "no hay nada apuntado").
# ----------------------------------------------------------------------------
SLOT_FORMAT = "<ii"
SLOT_SIZE = struct.calcsize(SLOT_FORMAT)

# Mismo razonamiento que en P1: se reduce de 4096 a 512 (permitido
# explicitamente por el enunciado) para que 100 registros de tamano variable
# fuercen la creacion de MUCHAS paginas y el codigo de "pagina llena -> nueva
# pagina" se ejercite realmente en las pruebas, no solo en un caso extremo
# dificil de alcanzar con pocos datos de prueba.
PAGE_SIZE = 512


class Matricula:
    """Registro logico pedido por el enunciado para P2: codigo y
    observaciones son de tamano variable (Cadena*), ciclo y mensualidad son
    de tamano fijo. Se modela igual que Alumno en P1: una clase Python
    "plana" separada del formato binario, para que el resto del codigo no
    tenga que pensar en bytes."""

    def __init__(self, codigo, ciclo, mensualidad, observaciones):
        self.codigo = codigo
        self.ciclo = ciclo
        self.mensualidad = mensualidad
        self.observaciones = observaciones

    def __repr__(self):
        return (f"Matricula({self.codigo!r}, ciclo={self.ciclo}, "
                f"mensualidad={self.mensualidad:.2f}, observaciones={self.observaciones!r})")


class RID:
    """Identico en espiritu al RID de P1: (page_id, slot_id). En SlottedPage
    el slot_id no es un offset directo a los datos, es un indice dentro del
    Slot Directory -- por eso sigue siendo estable aunque el registro se
    mueva fisicamente dentro de la pagina (ver compact())."""

    def __init__(self, page_id, slot_id):
        self.page_id = page_id
        self.slot_id = slot_id

    def __repr__(self):
        return f"RID(page={self.page_id}, slot={self.slot_id})"

    def __eq__(self, other):
        return self.page_id == other.page_id and self.slot_id == other.slot_id


def _pack_matricula(matricula):
    # ------------------------------------------------------------------
    # Formato binario del registro (independiente del formato de la pagina):
    #   <i        -> longitud de "codigo" en bytes (indicador de longitud,
    #                Tecnica 2 de la diapositiva)
    #   {n}s       -> los bytes de "codigo"
    #   i          -> ciclo (entero, tamano fijo, no necesita indicador)
    #   d          -> mensualidad (double, tamano fijo)
    #   i          -> longitud de "observaciones"
    #   {m}s       -> los bytes de "observaciones"
    #
    # POR QUE guardar la longitud ANTES de cada campo variable y no un
    # separador (como "|" en el ejemplo de texto de la diapositiva): un
    # separador exige recorrer byte a byte buscandolo (y falla si el
    # separador aparece dentro del propio dato, problema que la diapositiva
    # senala explicitamente: "El delimitador es parte del contenido"). Con
    # un indicador de longitud numerico, unpack sabe de antemano cuantos
    # bytes leer para cada campo, sin ambiguedad y sin escanear.
    # ------------------------------------------------------------------
    codigo_b = matricula.codigo.encode()
    obs_b = matricula.observaciones.encode()
    body_format = f"<i{len(codigo_b)}sid i{len(obs_b)}s".replace(" ", "")
    return struct.pack(
        body_format,
        len(codigo_b), codigo_b,
        matricula.ciclo,
        matricula.mensualidad,
        len(obs_b), obs_b,
    )


def _unpack_matricula(raw):
    # Se usa unpack_from con offsets manuales (en vez de un unico unpack con
    # formato fijo, como en P1) porque aqui el formato SI cambia de un
    # registro a otro (longitudes distintas de codigo/observaciones). Cada
    # "offset +=" avanza exactamente lo que _pack_matricula escribio para
    # ese campo -- por eso es indispensable el prefijo "<" (ver nota arriba):
    # sin el, estos calculos manuales podrian desalinearse del padding real.
    offset = 0
    (codigo_len,) = struct.unpack_from("<i", raw, offset)
    offset += struct.calcsize("<i")
    (codigo_b,) = struct.unpack_from(f"<{codigo_len}s", raw, offset)
    offset += codigo_len

    ciclo, mensualidad = struct.unpack_from("<id", raw, offset)
    offset += struct.calcsize("<id")

    (obs_len,) = struct.unpack_from("<i", raw, offset)
    offset += struct.calcsize("<i")
    (obs_b,) = struct.unpack_from(f"<{obs_len}s", raw, offset)

    return Matricula(codigo_b.decode(), ciclo, mensualidad, obs_b.decode())


class SlottedPage:
    def __init__(self, filename):
        self.filename = filename

        if not os.path.exists(filename) or os.path.getsize(filename) == 0:
            with open(filename, "wb") as f:
                f.write(struct.pack(FILE_HEADER_FORMAT, PAGE_SIZE, 0))

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
        num_slots, free_space_ptr = struct.unpack(PAGE_HEADER_FORMAT, data)
        return num_slots, free_space_ptr

    def _write_page_header(self, f, page_id, num_slots, free_space_ptr):
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, num_slots, free_space_ptr))

    def _slot_dir_offset(self, page_id, slot_id):
        # El Slot Directory vive INMEDIATAMENTE despues del Page Header y
        # CRECE HACIA ADELANTE (hacia offsets mayores) a medida que se
        # agregan registros -- tal como muestra la diapositiva "Estructura
        # de una Pagina - Reg. Long. Variable": "Page Header + ItemId Array
        # (Line Pointers)" arriba, "Tuple Data" abajo creciendo hacia arriba.
        return self._page_offset(page_id) + PAGE_HEADER_SIZE + slot_id * SLOT_SIZE

    def _read_slot_entry(self, f, page_id, slot_id):
        f.seek(self._slot_dir_offset(page_id, slot_id))
        data = f.read(SLOT_SIZE)
        offset, length = struct.unpack(SLOT_FORMAT, data)
        return offset, length

    def _write_slot_entry(self, f, page_id, slot_id, offset, length):
        f.seek(self._slot_dir_offset(page_id, slot_id))
        f.write(struct.pack(SLOT_FORMAT, offset, length))

    def _new_page(self, f, num_pages):
        # free_space_ptr = PAGE_SIZE al crear la pagina: el "limite" de la
        # zona de datos empieza justo al final de la pagina (todavia no se
        # escribio ningun registro), y bajara a medida que se inserten
        # registros desde el final hacia el inicio.
        page_id = num_pages
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, 0, PAGE_SIZE))
        f.write(b"\x00" * (PAGE_SIZE - PAGE_HEADER_SIZE))
        return page_id

    def _free_space(self, num_slots, free_space_ptr):
        # El espacio libre es lo que queda ENTRE donde termina el Slot
        # Directory (que crece hacia adelante) y donde empieza la zona de
        # datos ya ocupada (que crece hacia atras). Si ese numero llega a
        # ser menor que lo que necesita un nuevo registro + su slot, la
        # pagina esta "llena" aunque tenga tombstones con espacio
        # desperdiciado en el medio -- eso ES la fragmentacion que el
        # enunciado pide identificar (punto 3: "Fragmentacion").
        slot_dir_end = PAGE_HEADER_SIZE + num_slots * SLOT_SIZE
        return free_space_ptr - slot_dir_end

    def add(self, matricula):
        # ------------------------------------------------------------------
        # POR QUE first-fit (primera pagina que alcance) y no best-fit:
        # El enunciado solo exige "agrega un nuevo registro en una pagina
        # que tenga espacio suficiente. Si ninguna pagina puede alojarlo,
        # debera crear una nueva pagina" -- no exige minimizar fragmentacion
        # entre paginas, solo garantizar que el registro entre. first-fit es
        # la estrategia mas simple que cumple ese contrato.
        # ------------------------------------------------------------------
        raw = _pack_matricula(matricula)
        needed = SLOT_SIZE + len(raw)  # nueva entrada de directorio + los bytes del registro

        with open(self.filename, "r+b") as f:
            page_size, num_pages = self._read_file_header(f)

            target_page = None
            for page_id in range(num_pages):
                num_slots, free_space_ptr = self._read_page_header(f, page_id)
                if self._free_space(num_slots, free_space_ptr) >= needed:
                    target_page = page_id
                    break

            if target_page is None:
                # Si ni siquiera una pagina COMPLETAMENTE VACIA podria
                # alojar el registro, es un error del usuario (registro mas
                # grande que una pagina), no un caso a resolver creando
                # paginas encadenadas -- fuera del alcance del enunciado.
                if needed > PAGE_SIZE - PAGE_HEADER_SIZE - SLOT_SIZE:
                    raise ValueError("registro demasiado grande para una pagina")
                target_page = self._new_page(f, num_pages)
                num_pages += 1
                self._write_file_header(f, page_size, num_pages)

            num_slots, free_space_ptr = self._read_page_header(f, target_page)

            # Insercion "desde el final hacia el inicio" (tal como pide el
            # enunciado): el nuevo registro se escribe justo antes de donde
            # empezaba la zona de datos ya ocupada.
            record_offset = free_space_ptr - len(raw)
            f.seek(self._page_offset(target_page) + record_offset)
            f.write(raw)

            # El nuevo slot se agrega SIEMPRE al final del directorio actual
            # (nunca se reutiliza un tombstone en P2): a diferencia de P1
            # (donde FREE_LIST explicitamente reutiliza slots de tamano
            # fijo), en Slotted Page el espacio liberado por un registro
            # variable no necesariamente tiene el tamano exacto que necesita
            # un nuevo registro variable -- reutilizarlo sin cuidado
            # reintroduce el problema de fragmentacion interna. Se prefirio
            # dejar la recuperacion de espacio explicitamente a compact().
            slot_id = num_slots
            self._write_slot_entry(f, target_page, slot_id, record_offset, len(raw))
            self._write_page_header(f, target_page, num_slots + 1, record_offset)

            return RID(target_page, slot_id)

    def readRecord(self, rid):
        # O(1): el enunciado pide "obtiene el registro utilizando (page_id,
        # slot_id) y la informacion almacenada en el Slot Directory con
        # O(1)". Se valida el rango, se lee UNA entrada del directorio
        # (offset, length), y con eso se hace un unico seek+read a los bytes
        # exactos del registro -- sin escanear el resto de la pagina.
        with open(self.filename, "rb") as f:
            _, num_pages = self._read_file_header(f)
            if rid.page_id < 0 or rid.page_id >= num_pages:
                return None

            num_slots, _ = self._read_page_header(f, rid.page_id)
            if rid.slot_id < 0 or rid.slot_id >= num_slots:
                return None

            offset, length = self._read_slot_entry(f, rid.page_id, rid.slot_id)
            if length == -1:
                return None

            f.seek(self._page_offset(rid.page_id) + offset)
            raw = f.read(length)
            return _unpack_matricula(raw)

    def remove(self, rid):
        # ------------------------------------------------------------------
        # ESTRATEGIA DE ELIMINACION ELEGIDA PARA P2: eliminacion logica por
        # tombstone en el Slot Directory (length = -1), SIN mover ni borrar
        # los bytes fisicos del registro. Es la misma estrategia que muestra
        # el PDF de clase en la diapositiva "Demo: Insertar, Leer y Eliminar
        # en SlottedPage": tras p.delete(1), p.read(1) devuelve vacio, pero
        # el diagrama marca el Tuple 1 como "(eliminado) * espacio
        # recuperable con compact()" -- es decir, el dato sigue fisicamente
        # ahi hasta que se compacte.
        #
        # POR QUE no mover/comprimir en el momento del remove (como MOVE_LAST
        # en P1): en longitud variable no hay un "ultimo slot" de tamano
        # compatible para tapar el hueco (los registros tienen tamanos
        # distintos), y compactar en cada remove seria O(n) por operacion,
        # violando el requisito de remove() en O(1). Por eso se separa en
        # dos responsabilidades: remove() marca logicamente (O(1)),
        # compact() reorganiza fisicamente cuando se decide hacerlo (costo
        # asumido explicitamente, no escondido dentro de cada remove).
        # ------------------------------------------------------------------
        with open(self.filename, "r+b") as f:
            _, num_pages = self._read_file_header(f)
            if rid.page_id < 0 or rid.page_id >= num_pages:
                return False

            num_slots, _ = self._read_page_header(f, rid.page_id)
            if rid.slot_id < 0 or rid.slot_id >= num_slots:
                return False

            offset, length = self._read_slot_entry(f, rid.page_id, rid.slot_id)
            if length == -1:
                # Evita "doble eliminacion": ya es un tombstone.
                return False

            self._write_slot_entry(f, rid.page_id, rid.slot_id, offset, -1)
            return True

    def compact(self, page_id):
        # ------------------------------------------------------------------
        # Extension opcional que menciona el enunciado ("Como extension
        # opcional, se podra implementar compact() para reorganizar los
        # registros activos y consolidar el espacio libre"), tambien
        # sugerida por la diapositiva ("compact() reordena fisicamente sin
        # cambiar los slot_ids. Los indices no se invalidan").
        #
        # Algoritmo: se recolectan los bytes de todos los slots VIVOS
        # (length != -1) de la pagina, y se reescriben consecutivamente
        # desde el final de la pagina hacia el inicio (mismo sentido de
        # crecimiento que add()), actualizando cada entrada del Slot
        # Directory con su nuevo offset. Los tombstones simplemente se
        # dejan de escribir -- su espacio queda absorbido en la nueva zona
        # libre.
        #
        # POR QUE los slot_id (y por lo tanto los RID externos) NO cambian:
        # se itera "for slot_id in range(num_slots)" y se reescribe la
        # entrada de ESE MISMO slot_id con el nuevo offset -- nunca se
        # renumeran los slots. Esto es exactamente la garantia que pide la
        # diapositiva: un RID emitido antes de compact() sigue siendo valido
        # y apuntando al mismo registro logico despues.
        # ------------------------------------------------------------------
        with open(self.filename, "r+b") as f:
            num_slots, _ = self._read_page_header(f, page_id)

            entries = []
            for slot_id in range(num_slots):
                offset, length = self._read_slot_entry(f, page_id, slot_id)
                if length != -1:
                    f.seek(self._page_offset(page_id) + offset)
                    raw = f.read(length)
                    entries.append((slot_id, raw))

            write_ptr = PAGE_SIZE
            for slot_id, raw in entries:
                write_ptr -= len(raw)
                f.seek(self._page_offset(page_id) + write_ptr)
                f.write(raw)
                self._write_slot_entry(f, page_id, slot_id, write_ptr, len(raw))

            self._write_page_header(f, page_id, num_slots, write_ptr)

    def load(self):
        # Al igual que en P1, es el unico metodo intencionalmente O(n): el
        # enunciado pide "load(): devuelve todos los registros del archivo",
        # lo que exige tocar cada slot vivo al menos una vez.
        results = []
        with open(self.filename, "rb") as f:
            _, num_pages = self._read_file_header(f)
            for page_id in range(num_pages):
                num_slots, _ = self._read_page_header(f, page_id)
                for slot_id in range(num_slots):
                    offset, length = self._read_slot_entry(f, page_id, slot_id)
                    if length == -1:
                        continue
                    f.seek(self._page_offset(page_id) + offset)
                    raw = f.read(length)
                    results.append((RID(page_id, slot_id), _unpack_matricula(raw)))
        return results

    def print_headers(self, titulo=""):
        # Utilidad de depuracion/evidencia: igual que en P1, el enunciado
        # pide mostrar "el estado de una pagina antes y despues de las
        # operaciones" en las pruebas funcionales.
        with open(self.filename, "rb") as f:
            page_size, num_pages = self._read_file_header(f)
            print(f"--- {titulo} ---")
            print(f"FILE HEADER -> page_size={page_size}, num_pages={num_pages}")
            for page_id in range(num_pages):
                num_slots, free_space_ptr = self._read_page_header(f, page_id)
                libres = self._free_space(num_slots, free_space_ptr)
                print(f"  PAGE {page_id} -> num_slots={num_slots}, "
                      f"free_space_ptr={free_space_ptr}, free_space={libres}")
