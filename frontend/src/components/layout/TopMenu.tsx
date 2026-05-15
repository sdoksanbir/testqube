type TopMenuProps = {
  title?: string;
};

export default function TopMenu({ title = "TestQube" }: TopMenuProps) {
  return <div className="text-sm font-semibold text-slate-700">{title}</div>;
}
