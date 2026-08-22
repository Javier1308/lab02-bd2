# Opcion 2: archivo binario con registros de longitud fija
# Cada registro tiene una longitud fija de 28 bytes
# Se utiliza el módulo struct para empaquetar/desempaquetar los datos

import struct
import os

RECORD_FORMAT = "B5s11s20s15sid"
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)

FILE_HEADER_FORMAT = "ii"
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)

PAGE_HEADER_FORMAT = "iii"
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)

PAGE_SIZE = 512

SLOTS_PER_PAGE = (PAGE_SIZE - PAGE_HEADER_SIZE) // RECORD_SIZE


class Alumno:
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
    def __init__(self, page_id, slot_id):
        self.page_id = page_id
        self.slot_id = slot_id

    def __repr__(self):
        return f"RID(page={self.page_id}, slot={self.slot_id})"

    def __eq__(self, other):
        return self.page_id == other.page_id and self.slot_id == other.slot_id


class FixedRecord:
    def __init__(self, filename, mode="MOVE_LAST"):
        assert mode in ("MOVE_LAST", "FREE_LIST"), "modo invalido"
        self.filename = filename
        self.mode = mode

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
        num_records, num_active, free_list_head = struct.unpack(PAGE_HEADER_FORMAT, data)
        return num_records, num_active, free_list_head

    def _write_page_header(self, f, page_id, num_records, num_active, free_list_head):
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, num_records, num_active, free_list_head))

    def _slot_offset(self, page_id, slot_id):
        return self._page_offset(page_id) + PAGE_HEADER_SIZE + slot_id * RECORD_SIZE

    def _read_slot_raw(self, f, page_id, slot_id):
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
        page_id = num_pages
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, 0, 0, -1))
        f.write(b"\x00" * (PAGE_SIZE - PAGE_HEADER_SIZE))
        return page_id

    def add(self, alumno):
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
                target_page = self._new_page(f, num_pages)
                num_pages += 1
                self._write_file_header(f, page_size, num_pages)

            num_records, num_active, free_list_head = self._read_page_header(f, target_page)

            if self.mode == "FREE_LIST" and free_list_head != -1:
                slot_id = free_list_head
                _, _, _, _, _, next_free, _ = self._read_slot_raw(f, target_page, slot_id)
                new_free_list_head = next_free
                self._write_slot_raw(f, target_page, slot_id, self._pack_alumno(alumno))
                self._write_page_header(f, target_page, num_records, num_active + 1, new_free_list_head)
            else:
                slot_id = num_records
                self._write_slot_raw(f, target_page, slot_id, self._pack_alumno(alumno))
                self._write_page_header(f, target_page, num_records + 1, num_active + 1, free_list_head)

            return RID(target_page, slot_id)

    def readRecord(self, rid):
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
        with open(self.filename, "r+b") as f:
            _, num_pages = self._read_file_header(f)
            if rid.page_id < 0 or rid.page_id >= num_pages:
                return False

            num_records, num_active, free_list_head = self._read_page_header(f, rid.page_id)
            if rid.slot_id < 0 or rid.slot_id >= num_records:
                return False

            raw = self._read_slot_raw(f, rid.page_id, rid.slot_id)
            if raw[0] == 0:
                return False

            if self.mode == "MOVE_LAST":
                last_slot = num_active - 1
                if rid.slot_id != last_slot:
                    last_raw = self._read_slot_raw(f, rid.page_id, last_slot)
                    self._write_slot_raw(
                        f, rid.page_id, rid.slot_id,
                        struct.pack(RECORD_FORMAT, *last_raw),
                    )
                self._write_slot_raw(f, rid.page_id, last_slot, self._pack_free_node(-1))
                self._write_page_header(f, rid.page_id, num_records - 1, num_active - 1, free_list_head)
            else:
                self._write_slot_raw(f, rid.page_id, rid.slot_id, self._pack_free_node(free_list_head))
                self._write_page_header(f, rid.page_id, num_records, num_active - 1, rid.slot_id)

            return True

    def load(self):
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
        with open(self.filename, "rb") as f:
            page_size, num_pages = self._read_file_header(f)
            print(f"--- {titulo} ---")
            print(f"FILE HEADER -> page_size={page_size}, num_pages={num_pages}")
            for page_id in range(num_pages):
                num_records, num_active, free_list_head = self._read_page_header(f, page_id)
                print(f"  PAGE {page_id} -> num_records={num_records}, "
                      f"num_active={num_active}, free_list_head={free_list_head}")
