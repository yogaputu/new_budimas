-- Archive and clear legacy voucher/promo data after switching to Promo All-In.
-- Run only after a database backup is confirmed.

DO $$
DECLARE
    table_name text;
    backup_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'voucher_1',
        'voucher_2',
        'voucher_3',
        'draft_voucher',
        'draft_voucher_2',
        'trade_promo_rule_product',
        'trade_promo_program_rule',
        'trade_promo_program'
    ]
    LOOP
        IF to_regclass(table_name) IS NOT NULL THEN
            backup_name := 'legacy_backup_' || table_name || '_20260517';
            EXECUTE format('CREATE TABLE IF NOT EXISTS %I AS TABLE %I WITH NO DATA', backup_name, table_name);
            EXECUTE format('INSERT INTO %I SELECT * FROM %I', backup_name, table_name);
            EXECUTE format('TRUNCATE TABLE %I RESTART IDENTITY CASCADE', table_name);
        END IF;
    END LOOP;
END $$;
