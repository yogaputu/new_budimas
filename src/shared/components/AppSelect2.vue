<script>
import { defineComponent, h, nextTick, ref } from 'vue';
import AppSearchSelect from './AppSearchSelect.vue';
import { selectOptions, selectedOptionValues } from '../utils/selectOptions';

// Compatibility adapter for existing select forms: keep option values, .number,
// @change events and native form validation while using the shared searchable UI.
export default defineComponent({
  name: 'AppSelect2',
  inheritAttrs: false,
  props: {
    modelValue: { type: [String, Number, Boolean, Array], default: '' },
    modelModifiers: { type: Object, default: () => ({}) },
    multiple: Boolean,
    disabled: Boolean,
    required: Boolean,
    label: { type: String, default: '' },
    placeholder: { type: String, default: '' },
    loading: Boolean
  },
  emits: ['update:modelValue', 'change', 'blur', 'focus'],
  setup(props, { attrs, slots, emit, expose }) {
    const control = ref(null), native = ref(null);
    function syncNative(value = props.modelValue) {
      if (!native.value) return;
      if (props.multiple) {
        const values = Array.isArray(value) ? value : [];
        for (const option of native.value.options) option.selected = values.some(v => String(v) === option.value);
      } else {
        native.value.selectedIndex = [...native.value.options].findIndex(option => String(value ?? '') === option.value);
      }
    }
    function update(value, options) {
      const typed = props.multiple ? selectedOptionValues(value, options, true) : value;
      emit('update:modelValue', typed);
      syncNative(typed);
      native.value?.dispatchEvent(new Event('change', { bubbles: true }));
    }
    expose({ focus: () => control.value?.focus() });
    return () => {
      const options = selectOptions(slots.default?.() || []);
      const empty = options.find(option => option.value === '');
      return h('div', { class: ['app-select2 min-w-0', attrs.class], style: attrs.style }, [
        h(AppSearchSelect, {
          ref: control, modelValue: props.modelValue, options, multiple: props.multiple,
          disabled: props.disabled, loading: props.loading, label: props.label,
          ariaLabel: attrs['aria-label'] || props.label,
          labelledBy: attrs['aria-labelledby'], inputId: attrs.id,
          placeholder: props.placeholder || empty?.label || 'Cari / pilih data',
          clearSearchOnOpen: true, clearable: props.multiple || Boolean(empty), optionPageSize: 50, dropdownPortal: true,
          'onUpdate:modelValue': value => update(value, options),
          onFocus: event => emit('focus', event), onBlur: event => emit('blur', event)
        }),
        h('select', {
          ref: native, class: 'sr-only', tabindex: -1, 'aria-hidden': 'true',
          name: attrs.name, required: props.required, disabled: props.disabled, multiple: props.multiple,
          onChange: event => emit('change', event),
          onInvalid: event => { event.preventDefault(); control.value?.focus(); },
          onVnodeMounted: () => nextTick(() => syncNative()), onVnodeUpdated: () => syncNative()
        }, options.map(option => h('option', { value: option.value, disabled: option.disabled }, option.label)))
      ]);
    };
  }
});
</script>
