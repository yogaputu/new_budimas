// Read rendered <option> slots without changing their bound value types.
export function selectOptions(nodes = [], inheritedDisabled = false) {
  return nodes.flatMap(node => {
    if (!node || typeof node !== 'object') return [];
    const disabled = inheritedDisabled || (node.props?.disabled != null && node.props.disabled !== false);
    if (node.type === 'option') {
      const label = optionText(node.children).replace(/\s+/g, ' ').trim();
      return [{ value: node.props?.value ?? label, label, disabled }];
    }
    return Array.isArray(node.children) ? selectOptions(node.children, disabled) : [];
  });
}

function optionText(children) {
  if (typeof children === 'string' || typeof children === 'number') return String(children);
  if (!Array.isArray(children)) return '';
  return children.map(child => typeof child === 'object' ? optionText(child?.children) : optionText(child)).join('');
}

export function selectedOptionValues(value, options, multiple = false) {
  const values = multiple ? (Array.isArray(value) ? value : []) : [value];
  return options.filter(option => values.some(v => String(v) === String(option.value))).map(option => option.value);
}
