// Campos de archivo en español: el botón nativo ("Choose files") depende del idioma del navegador y no se puede
// cambiar con CSS. Se oculta el control nativo (sigue enviando el archivo) y se muestra un botón y un estado propios.
// Sin JavaScript queda el control nativo.
for (const input of document.querySelectorAll('input[type="file"]')) {
  const vacio = "Ningún archivo seleccionado";
  const caja = document.createElement("span");
  caja.className = "selector-archivo";
  const boton = document.createElement("button");
  boton.type = "button";
  boton.className = "boton";
  boton.textContent = input.multiple ? "Elegir archivos" : "Elegir archivo";
  if (input.labels && input.labels.length) {
    boton.setAttribute("aria-label", `${boton.textContent}: ${input.labels[0].textContent.trim()}`);
  }
  const estado = document.createElement("span");
  estado.className = "selector-archivo-estado";
  estado.setAttribute("aria-live", "polite");

  const actualizar = () => {
    const n = input.files.length;
    estado.textContent = n === 0 ? vacio : n === 1 ? input.files[0].name : `${n} archivos seleccionados`;
    estado.title = Array.from(input.files, (f) => f.name).join("\n");
  };

  input.classList.add("sr-only");
  input.tabIndex = -1;
  input.after(caja);
  caja.append(boton, estado);
  boton.addEventListener("click", () => input.click());
  input.addEventListener("change", actualizar);
  actualizar();
}
