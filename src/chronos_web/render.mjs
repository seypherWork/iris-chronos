import {consentView} from "./consent.mjs";
import {decisionDetailView, appendDetailSections, appendResultRows} from "./detail.mjs";
import {decisionView, operationView, previewView} from "./presentation.mjs";

/**
 * No HTML templates, links, user-controlled tag names, event handlers or actions.
 * Only raw API envelopes enter; callers cannot supply prebuilt render models.
 */
export function renderResult(container, kind, envelope, context) {
  const projectors = {consent: consentView, detail: decisionDetailView, decision: decisionView, operation: operationView, preview: previewView};
  if (!Object.hasOwn(projectors, kind)) throw new TypeError("Unknown result kind");
  const view = projectors[kind](envelope, context);
  const document = container.ownerDocument;
  const make = (tag, text, parent) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (parent) parent.appendChild(element);
    return element;
  };
  const build = model => {
    const section = make("section");
    section.className = "chronos-result chronos-result--" + model.tone;
    section.setAttribute("aria-label", model.kind + " result");
    make("p", model.evidenceLabel, section).className = "chronos-provenance";
    make("h2", model.title, section);
    make("p", model.summary, section);
    if (model.kind !== "detail") appendResultRows(document, section, model);
    appendDetailSections(document, section, model.sections);
    if (model.kind === "detail") appendResultRows(document, section, model);
    if (model.operation) section.appendChild(build(model.operation));
    return section;
  };
  container.replaceChildren(build(view));
  return view;
}
