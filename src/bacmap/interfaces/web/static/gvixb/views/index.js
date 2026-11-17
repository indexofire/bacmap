/**
 * The single view registry.
 *
 * Everything that needs the published view list (auto entry, framework,
 * manifest checks, tests) imports VIEWS from here. Adding a view is one import
 * plus one entry in `runtime/manifest.json`.
 */
import { assemblyView } from './assembly-view.js';
import { circularAnnotationView } from './circular-annotation-view.js';
import { phyloView } from './phylo-view.js';
import { mstView } from './mst-view.js';

export const VIEWS = [assemblyView, circularAnnotationView, phyloView, mstView];

export const VIEW_IDS = VIEWS.map(view => view.id);
