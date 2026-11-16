// Campos de archivo en español: el botón nativo ("Choose files") depende del idioma del navegador y no se puede
// cambiar con CSS. Se oculta el control nativo (sigue enviando el archivo) y se muestra un botón y un estado propios.
// Sin JavaScript queda el control nativo.
// En los campos múltiples, elegir o arrastrar archivos se SUMA a lo ya elegido (el control nativo los reemplaza),
// así se pueden juntar archivos de varias carpetas antes de cargar. Cada archivo elegido se puede quitar.
for (const input of document.querySelectorAll('input[type="file"]')) {
  const vacio = "Ningún archivo seleccionado";
  const caja = document.createElement("span");
  caja.className = "selector-archivo";
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "boton";
  boton.textContent = input.multiple ? "Agregar archivos" : "Elegir archivo";
  if (input.labels && input.labels.length) {
    boton.setAttribute("aria-label", `${boton.textContent}: ${input.labels[0].textContent.trim()}`);
  }
  const estado = document.createElement("span");
  estado.className = "selector-archivo-estado";
  estado.setAttribute("aria-live", "polite");
  const lista = document.createElement("ul");
  lista.className = "lista-archivos";

  const elegidos = new DataTransfer();
  const extensiones = (input.accept || "").split(",").map((e) => e.trim().toLowerCase()).filter(Boolean);
  const aceptado = (f) => !extensiones.length || extensiones.some((e) => f.name.toLowerCase().endsWith(e));
  const igual = (a, b) => a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;

  const actualizar = () => {
    const n = input.files.length;
    estado.textContent = n === 0 ? vacio : n === 1 ? input.files[0].name : `${n} archivos seleccionados`;
    estado.title = Array.from(input.files, (f) => f.name).join("\n");
    if (!input.multiple) return;
    lista.replaceChildren(...Array.from(elegidos.files, (f, i) => {
      const li = document.createElement("li");
      const quitar = document.createElement("button");
      quitar.type = "button";
      quitar.className = "boton boton-peligro";
      quitar.textContent = "Quitar";
      quitar.setAttribute("aria-label", `Quitar ${f.name}`);
      quitar.addEventListener("click", () => {
        elegidos.items.remove(i);
        input.files = elegidos.files;
        actualizar();
      });
      li.append(f.name, quitar);
      return li;
    }));
  };

  const agregar = (archivos) => {
    const rechazados = [];
    for (const f of archivos) {
      if (!aceptado(f)) rechazados.push(f.name);
      else if (!Array.from(elegidos.files).some((g) => igual(f, g))) elegidos.items.add(f);
    }
    input.files = elegidos.files;
    actualizar();
    if (rechazados.length) alert(`No se agregaron (solo ${extensiones.join(", ")}):\n${rechazados.join("\n")}`);
  };

  input.classList.add("sr-only");
  input.tabIndex = -1;
  input.after(caja);
  caja.append(boton, estado);
  boton.addEventListener("click", () => input.click());
  if (input.multiple) {
    caja.after(lista);
    input.addEventListener("change", () => agregar(input.files));
    const zona = input.closest(".n-zona-carga");
    if (zona) {
      const ayuda = document.createElement("span");
      ayuda.className = "n-ayuda";
      ayuda.textContent = "También puedes arrastrar los archivos hasta este recuadro.";
      caja.before(ayuda);
      zona.addEventListener("dragover", (e) => { e.preventDefault(); zona.classList.add("arrastrando"); });
      zona.addEventListener("dragleave", (e) => { if (!zona.contains(e.relatedTarget)) zona.classList.remove("arrastrando"); });
      zona.addEventListener("drop", (e) => {
        e.preventDefault();
        zona.classList.remove("arrastrando");
        agregar(e.dataTransfer.files);
      });
    }
  } else {
    input.addEventListener("change", actualizar);
  }
  actualizar();
}

// Un archivo soltado fuera del recuadro no debe abrirse en el navegador (se perdería lo ya elegido).
for (const tipo of ["dragover", "drop"]) {
  window.addEventListener(tipo, (e) => { if (!e.defaultPrevented) e.preventDefault(); });
}
