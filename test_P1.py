import os

from P1 import Alumno, RID, FixedRecord, SLOTS_PER_PAGE

N_REGISTROS = 100


def nuevo_alumno(i):
    return Alumno(
        codigo=f"C{i:04d}",
        nombre=f"Nombre{i}",
        apellidos=f"Apellido{i}",
        carrera="Sistemas",
        ciclo=(i % 10) + 1,
        mensualidad=500.0 + i,
    )


def test_insercion_y_paginacion(archivo, modo):
    print(f"\n===== TEST insercion/paginacion ({modo}) =====")
    if os.path.exists(archivo):
        os.remove(archivo)

    hf = FixedRecord(archivo, mode=modo)
    hf.print_headers("Antes de insertar")

    rids = []
    for i in range(N_REGISTROS):
        rid = hf.add(nuevo_alumno(i))
        rids.append(rid)

    hf.print_headers("Despues de insertar")

    registros = hf.load()
    assert len(registros) == N_REGISTROS, f"esperaba {N_REGISTROS}, obtuve {len(registros)}"

    with open(archivo, "rb") as f:
        _, num_pages = hf._read_file_header(f)
    assert num_pages > 1, "se esperaban multiples paginas para 100 registros"
    print(f"OK: {N_REGISTROS} registros repartidos en {num_pages} paginas "
          f"({SLOTS_PER_PAGE} slots/pagina)")

    return hf, rids


def test_lectura(hf, rids):
    print("\n===== TEST readRecord =====")
    for idx in (0, 37, 99):
        rid = rids[idx]
        alumno = hf.readRecord(rid)
        assert alumno is not None
        assert alumno.codigo == f"C{idx:04d}"
        print(f"OK: {rid} -> {alumno}")

    rid_invalido_pagina = RID(999, 0)
    rid_invalido_slot = RID(0, 999)
    assert hf.readRecord(rid_invalido_pagina) is None
    assert hf.readRecord(rid_invalido_slot) is None
    print("OK: readRecord con RID invalido devuelve None")


def test_move_the_last(archivo):
    print("\n===== TEST MOVE THE LAST =====")
    hf, rids = test_insercion_y_paginacion(archivo, "MOVE_LAST")
    test_lectura(hf, rids)

    rid_borrar = rids[50]
    page_id = rid_borrar.page_id
    with open(archivo, "rb") as f:
        num_records_antes, num_active_antes, _ = hf._read_page_header(f, page_id)
    ultimo_activo_rid = RID(page_id, num_active_antes - 1)
    ultimo_activo = hf.readRecord(ultimo_activo_rid)
    assert ultimo_activo is not None

    hf.print_headers("Antes de eliminar (MOVE_LAST)")
    ok = hf.remove(rid_borrar)
    hf.print_headers("Despues de eliminar (MOVE_LAST)")
    assert ok

    movido = hf.readRecord(rid_borrar)
    assert movido is not None
    assert movido.codigo == ultimo_activo.codigo, "el ultimo activo debio moverse al slot eliminado"
    print(f"OK: registro {ultimo_activo.codigo} se movio a {rid_borrar}")

    with open(archivo, "rb") as f:
        num_records_despues, num_active_despues, _ = hf._read_page_header(f, page_id)
    assert num_active_despues == num_active_antes - 1
    assert num_records_despues == num_records_antes - 1
    print("OK: num_records y num_active decrementados en la pagina afectada")

    assert len(hf.load()) == N_REGISTROS - 1

    assert hf.remove(RID(999, 0)) is False
    assert hf.remove(RID(0, 999)) is False
    print("OK: remove con RID invalido devuelve False")


def test_free_list(archivo):
    print("\n===== TEST FREE LIST =====")
    hf, rids = test_insercion_y_paginacion(archivo, "FREE_LIST")
    test_lectura(hf, rids)

    borrados = [rids[1], rids[3], rids[5]]
    page_id = borrados[0].page_id
    assert all(r.page_id == page_id for r in borrados), "ajustar prueba: se espera misma pagina"

    hf.print_headers("Antes de eliminar (FREE_LIST)")
    for rid in borrados:
        assert hf.remove(rid)
    hf.print_headers("Despues de eliminar (FREE_LIST)")

    with open(archivo, "rb") as f:
        _, _, free_list_head = hf._read_page_header(f, page_id)
    assert free_list_head == borrados[-1].slot_id, "free_list_head debe apuntar al ultimo eliminado (LIFO)"
    print(f"OK: free_list_head={free_list_head} (LIFO, ultimo eliminado primero)")

    assert len(hf.load()) == N_REGISTROS - len(borrados)

    nuevos = [hf.add(nuevo_alumno(1000 + i)) for i in range(len(borrados))]
    slots_reusados = [rid.slot_id for rid in nuevos]
    esperado = [r.slot_id for r in reversed(borrados)]
    assert slots_reusados == esperado, f"se esperaba reuso LIFO {esperado}, obtuve {slots_reusados}"
    print(f"OK: slots reutilizados en orden LIFO {slots_reusados}")

    assert len(hf.load()) == N_REGISTROS
    print("OK: total de registros vuelve a 100 tras reinsercion")


def main():
    archivo_ml = "prueba_move_last.dat"
    archivo_fl = "prueba_free_list.dat"

    test_move_the_last(archivo_ml)
    test_free_list(archivo_fl)

    for f in (archivo_ml, archivo_fl):
        if os.path.exists(f):
            os.remove(f)

    print("\nTODOS LOS TESTS DE P1 PASARON")


if __name__ == "__main__":
    main()
