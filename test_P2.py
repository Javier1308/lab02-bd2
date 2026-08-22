import os

from P2 import Matricula, RID, SlottedPage

N_REGISTROS = 100
ARCHIVO = "prueba_slotted.dat"


def nueva_matricula(i):
    # observaciones de tamano variable para forzar registros de distinto largo
    obs = ("sin observaciones" if i % 3 == 0 else f"observacion detallada numero {i} " * (1 + i % 4))
    return Matricula(
        codigo=f"MAT-{i:05d}",
        ciclo=(i % 10) + 1,
        mensualidad=450.0 + i,
        observaciones=obs,
    )


def test_insercion_multiples_paginas(sp):
    print("\n===== TEST insercion en varias paginas (tamanos variables) =====")
    sp.print_headers("Antes de insertar")

    rids = []
    for i in range(N_REGISTROS):
        rid = sp.add(nueva_matricula(i))
        rids.append(rid)

    sp.print_headers("Despues de insertar")

    registros = sp.load()
    assert len(registros) == N_REGISTROS, f"esperaba {N_REGISTROS}, obtuve {len(registros)}"

    with open(ARCHIVO, "rb") as f:
        _, num_pages = sp._read_file_header(f)
    assert num_pages > 1, "se esperaban multiples paginas para 100 registros de tamano variable"
    print(f"OK: {N_REGISTROS} registros de tamanos distintos repartidos en {num_pages} paginas")

    return rids


def test_lectura_por_rid(sp, rids):
    print("\n===== TEST readRecord por RID =====")
    for idx in (0, 37, 99):
        rid = rids[idx]
        m = sp.readRecord(rid)
        assert m is not None
        assert m.codigo == f"MAT-{idx:05d}"
        print(f"OK: {rid} -> {m}")

    rid_invalido_pagina = RID(999, 0)
    rid_invalido_slot = RID(0, 999)
    assert sp.readRecord(rid_invalido_pagina) is None
    assert sp.readRecord(rid_invalido_slot) is None
    print("OK: readRecord con RID invalido devuelve None")


def test_eliminacion_logica_y_slot_directory(sp, rids):
    print("\n===== TEST eliminacion logica + Slot Directory =====")
    rid = rids[10]
    page_id = rid.page_id

    with open(ARCHIVO, "rb") as f:
        offset_antes, length_antes = sp._read_slot_entry(f, page_id, rid.slot_id)
    assert length_antes != -1
    print(f"Slot antes de eliminar: offset={offset_antes}, length={length_antes}")

    sp.print_headers("Antes de eliminar")
    ok = sp.remove(rid)
    sp.print_headers("Despues de eliminar")
    assert ok

    with open(ARCHIVO, "rb") as f:
        offset_despues, length_despues = sp._read_slot_entry(f, page_id, rid.slot_id)
    assert length_despues == -1, "el slot debe quedar marcado como tombstone (length=-1)"
    assert offset_despues == offset_antes, "la eliminacion logica no debe mover el registro fisicamente"
    print(f"OK: Slot Directory marca tombstone -> offset={offset_despues}, length={length_despues}")

    assert sp.readRecord(rid) is None, "readRecord no debe devolver un registro eliminado"
    print("OK: readRecord(rid_eliminado) devuelve None")

    registros = sp.load()
    assert all(r != rid for r, _ in registros), "load() no debe incluir registros eliminados"
    assert len(registros) == N_REGISTROS - 1
    print(f"OK: load() devuelve {len(registros)} registros (excluye el eliminado)")

    assert sp.remove(RID(999, 0)) is False
    assert sp.remove(RID(0, 999)) is False
    assert sp.remove(rid) is False, "no se puede eliminar dos veces el mismo slot"
    print("OK: remove sobre RID invalido o ya eliminado devuelve False")

    return page_id


def test_fragmentacion_y_compact(sp, rids, page_id):
    print("\n===== TEST fragmentacion y compact() =====")

    otros_en_pagina = [r for r in rids if r.page_id == page_id and r.slot_id != rids[10].slot_id][:2]
    for r in otros_en_pagina:
        sp.remove(r)

    with open(ARCHIVO, "rb") as f:
        num_slots, free_space_ptr = sp._read_page_header(f, page_id)
    espacio_libre_antes = sp._free_space(num_slots, free_space_ptr)
    print(f"Fragmentacion: espacio 'libre' contiguo antes de compact() = {espacio_libre_antes} bytes "
          f"(el espacio de los tombstones NO se reutiliza sin compact)")

    vivos_antes = {rid.slot_id: m for rid, m in sp.load() if rid.page_id == page_id}

    sp.print_headers(f"Pagina {page_id} antes de compact()")
    sp.compact(page_id)
    sp.print_headers(f"Pagina {page_id} despues de compact()")

    with open(ARCHIVO, "rb") as f:
        num_slots2, free_space_ptr2 = sp._read_page_header(f, page_id)
    espacio_libre_despues = sp._free_space(num_slots2, free_space_ptr2)
    assert espacio_libre_despues > espacio_libre_antes, "compact() debe recuperar espacio libre"
    print(f"OK: espacio libre crecio de {espacio_libre_antes} a {espacio_libre_despues} bytes tras compact()")

    vivos_despues = {rid.slot_id: m for rid, m in sp.load() if rid.page_id == page_id}
    assert set(vivos_antes.keys()) == set(vivos_despues.keys()), "los RID (slot_id) no deben cambiar tras compact()"
    for slot_id, m_antes in vivos_antes.items():
        m_despues = vivos_despues[slot_id]
        assert m_antes.codigo == m_despues.codigo, "los datos deben preservarse tras compact()"
    print("OK: compact() preserva RIDs externos y contenido de los registros vivos")


def main():
    if os.path.exists(ARCHIVO):
        os.remove(ARCHIVO)

    sp = SlottedPage(ARCHIVO)

    rids = test_insercion_multiples_paginas(sp)
    test_lectura_por_rid(sp, rids)
    page_id = test_eliminacion_logica_y_slot_directory(sp, rids)
    test_fragmentacion_y_compact(sp, rids, page_id)

    if os.path.exists(ARCHIVO):
        os.remove(ARCHIVO)

    print("\nTODOS LOS TESTS DE P2 PASARON")


if __name__ == "__main__":
    main()
