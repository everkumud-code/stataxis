# Button theme

Two looks, both changing only the controls (shape and light), never the page colours.

- **Public website** (`dashboard/skeuo.css`, pulled in by `tech.css` with one `@import`, and linked by login, forgot, apply, unsubscribe and the poll pages): skeuomorphic keys after the owner's kit picture. Raised, bevelled buttons with a lit top edge and a dark underside that press in when used, glossy convex solid buttons, round knobs (menu button, FAQ marks), sunk-in check boxes and radios with a lit mark, key-like poll scale buttons and option tiles. Every colour stays the page's own (blue stays blue, dark glass stays dark).
- **Dashboard / workspace** (`dashboard/ws3d.css`, linked from `workspace.html`): white 3D keys with a lit rim, round-edged, pressing in when used; the main action has a yellow rim; a key that is switched on (open tab) is pressed and lit yellow. A row that holds two or more buttons and nothing else sits on a yellow strip (like keys on a rail), including the two top-bar buttons. Check boxes and radios become white 3D with a yellow mark. The dark theme is unchanged.

Print rules still hide every button. Reduced-motion users get no movement. To change a look, edit those two files only.
