import struct
import os

FILE_HEADER_FORMAT = "<ii"
FILE_HEADER_SIZE = struct.calcsize(FILE_HEADER_FORMAT)

PAGE_HEADER_FORMAT = "<ii"
PAGE_HEADER_SIZE = struct.calcsize(PAGE_HEADER_FORMAT)

SLOT_FORMAT = "<ii"
SLOT_SIZE = struct.calcsize(SLOT_FORMAT)

PAGE_SIZE = 512


class Matricula:
    def __init__(self, codigo, ciclo, mensualidad, observaciones):
        self.codigo = codigo
        self.ciclo = ciclo
        self.mensualidad = mensualidad
        self.observaciones = observaciones

    def __repr__(self):
        return (f"Matricula({self.codigo!r}, ciclo={self.ciclo}, "
                f"mensualidad={self.mensualidad:.2f}, observaciones={self.observaciones!r})")


class RID:
    def __init__(self, page_id, slot_id):
        self.page_id = page_id
        self.slot_id = slot_id

    def __repr__(self):
        return f"RID(page={self.page_id}, slot={self.slot_id})"

    def __eq__(self, other):
        return self.page_id == other.page_id and self.slot_id == other.slot_id


def _pack_matricula(matricula):
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
        page_id = num_pages
        f.seek(self._page_offset(page_id))
        f.write(struct.pack(PAGE_HEADER_FORMAT, 0, PAGE_SIZE))
        f.write(b"\x00" * (PAGE_SIZE - PAGE_HEADER_SIZE))
        return page_id

    def _free_space(self, num_slots, free_space_ptr):
        slot_dir_end = PAGE_HEADER_SIZE + num_slots * SLOT_SIZE
        return free_space_ptr - slot_dir_end

    def add(self, matricula):
        raw = _pack_matricula(matricula)
        needed = SLOT_SIZE + len(raw)

        with open(self.filename, "r+b") as f:
            page_size, num_pages = self._read_file_header(f)

            target_page = None
            for page_id in range(num_pages):
                num_slots, free_space_ptr = self._read_page_header(f, page_id)
                if self._free_space(num_slots, free_space_ptr) >= needed:
                    target_page = page_id
                    break

            if target_page is None:
                if needed > PAGE_SIZE - PAGE_HEADER_SIZE - SLOT_SIZE:
                    raise ValueError("registro demasiado grande para una pagina")
                target_page = self._new_page(f, num_pages)
                num_pages += 1
                self._write_file_header(f, page_size, num_pages)

            num_slots, free_space_ptr = self._read_page_header(f, target_page)

            record_offset = free_space_ptr - len(raw)
            f.seek(self._page_offset(target_page) + record_offset)
            f.write(raw)

            slot_id = num_slots
            self._write_slot_entry(f, target_page, slot_id, record_offset, len(raw))
            self._write_page_header(f, target_page, num_slots + 1, record_offset)

            return RID(target_page, slot_id)

    def readRecord(self, rid):
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
        with open(self.filename, "r+b") as f:
            _, num_pages = self._read_file_header(f)
            if rid.page_id < 0 or rid.page_id >= num_pages:
                return False

            num_slots, _ = self._read_page_header(f, rid.page_id)
            if rid.slot_id < 0 or rid.slot_id >= num_slots:
                return False

            offset, length = self._read_slot_entry(f, rid.page_id, rid.slot_id)
            if length == -1:
                return False

            self._write_slot_entry(f, rid.page_id, rid.slot_id, offset, -1)
            return True

    def compact(self, page_id):
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
        with open(self.filename, "rb") as f:
            page_size, num_pages = self._read_file_header(f)
            print(f"--- {titulo} ---")
            print(f"FILE HEADER -> page_size={page_size}, num_pages={num_pages}")
            for page_id in range(num_pages):
                num_slots, free_space_ptr = self._read_page_header(f, page_id)
                libres = self._free_space(num_slots, free_space_ptr)
                print(f"  PAGE {page_id} -> num_slots={num_slots}, "
                      f"free_space_ptr={free_space_ptr}, free_space={libres}")
