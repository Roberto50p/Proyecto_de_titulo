// Recuadro de corrección bajo cada venta anómala: se abre con el botón "Resolver" o haciendo clic en la fila.
// Al guardar, la página vuelve a la fila con el recuadro cerrado; si no se pudo guardar, vuelve con él abierto.
// Sin JavaScript el recuadro no se oculta.
const alternar = (fila, abrir) => {
  const recuadro = document.getElementById(fila.dataset.recuadro);
  const boton = fila.querySelector(".boton-recuadro");
  abrir = abrir ?? recuadro.hidden;
  recuadro.hidden = !abrir;
  boton.setAttribute("aria-expanded", String(abrir));
};

for (const fila of document.querySelectorAll("tr.fila-corregible")) {
  fila.addEventListener("click", (e) => {
    if (e.target.closest("a, input, select, textarea") || (e.target.closest("button") && !e.target.closest(".boton-recuadro"))) return;
    alternar(fila);
  });
}

for (const form of document.querySelectorAll("form.form-correccion")) {
  const aceptada = form.querySelector('input[name="aceptada"]');
  const datos = form.querySelectorAll('[name="documento"], [name="monto"], [name="cod_deb"], [name="fecha_bordero"]');
  // Aceptar sin corregir: los datos del bordero no se usan (el servidor los descarta).
  const segunAceptada = () => { if (aceptada) datos.forEach((c) => { c.disabled = aceptada.checked; }); };
  aceptada?.addEventListener("change", segunAceptada);
  segunAceptada();
}

// Volver a la venta tras guardar (#v123: fila, recuadro cerrado) o si no se pudo guardar (#c123: recuadro abierto).
const destino = location.hash && document.getElementById(decodeURIComponent(location.hash.slice(1)));
const fila = destino && (destino.matches("tr.fila-corregible") ? destino
  : document.querySelector(`tr.fila-corregible[data-recuadro="${CSS.escape(destino.id)}"]`));
if (fila) {
  const seccion = fila.closest("details");  // Corregidas está plegada
  if (seccion) seccion.open = true;
  if (fila !== destino) alternar(fila, true);
  fila.scrollIntoView({ block: "center" });
}
