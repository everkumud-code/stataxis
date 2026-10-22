# Button theme

Two looks, both changing only the controls (shape and light), never the page colours.

- **Public website** (`dashboard/skeuo.css`, pulled in by `tech.css` with one `@import`, and linked by login, forgot, apply, unsubscribe and the poll pages): skeuomorphic keys after the owner's kit picture. Raised, bevelled buttons with a lit top edge and a dark underside that press in when used, glossy convex solid buttons, round knobs (menu button, FAQ marks), sunk-in check boxes and radios with a lit mark, key-like poll scale buttons and option tiles. Every colour stays the page's own (blue stays blue, dark glass stays dark).
- **Dashboard / workspace** (`dashboard/ws3d.css`, linked from `workspace.html`): dark glass keys after the owner's power-button picture (22 Oct 2026, replacing the white-keys-on-yellow-strip look). A near-black capsule with a lit top edge and a deep underside, outlined by a fine blue-to-cyan line; the main action has a brighter cyan rim and glow; a key that is switched on (open tab) glows from inside; keys press in when used. Check boxes and radios are dark wells with a glowing cyan ring and mark. There is no strip behind the keys. The dark theme of the page is unchanged.

Print rules still hide every button. Reduced-motion users get no movement. To change a look, edit those two files only.
