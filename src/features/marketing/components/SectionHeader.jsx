/* The eyebrow + display headline that opens each landing-page section.
   `children` is the headline (spans and <br>s included); the sub-paragraph
   stays at the call site because its size differs per section. */
export function SectionHeader({ eyebrow, children }) {
  return (
    <div>
      {eyebrow && (
        <p className="mb-4 text-[11px] font-bold uppercase tracking-[0.15em] text-accent">
          {eyebrow}
        </p>
      )}
      <h2 className="font-display text-[clamp(2rem,4vw,2.75rem)] font-bold leading-[1.05] tracking-[-0.03em]">
        {children}
      </h2>
    </div>
  );
}
