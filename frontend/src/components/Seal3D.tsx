import type { CSSProperties, ReactElement } from "react";

/*
 * The "visto" (aval) as a 3D stamp: 27 stacked layers give the disc its thickness, the face
 * carries the ring text and the coral check. It wobbles and floats gently on its own; the
 * animation is dropped under prefers-reduced-motion (see styles.css). Decorative, so aria-hidden.
 */
const LAYERS = Array.from({ length: 27 }, (_, index) => index - 13);

export function Seal3D(): ReactElement {
  return (
    <div className="seal3d-stage" aria-hidden="true">
      <div className="seal3d">
        {LAYERS.map((z) => (
          <div className="seal3d__layer" key={z} style={{ "--z": z } as CSSProperties} />
        ))}
        <div className="seal3d__face">
          <svg viewBox="0 0 200 200">
            <defs>
              <path id="seal3d-ring" d="M100,100 m-82,0 a82,82 0 1,1 164,0 a82,82 0 1,1 -164,0" />
            </defs>
            <g className="seal3d__ring">
              <text>
                <textPath href="#seal3d-ring">APROVADO COM O SEU AVAL &#183; APROVADO COM O SEU AVAL &#183; </textPath>
              </text>
            </g>
            <path className="seal3d__check" d="M52 104c10 7 18 16 24 25C92 98 118 76 152 66" />
          </svg>
        </div>
        <div className="seal3d__back" />
      </div>
      <div className="seal3d__shadow" />
    </div>
  );
}
