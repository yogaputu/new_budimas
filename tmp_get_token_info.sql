SELECT id, nama, left(tokens, 20) AS token_prefix, length(tokens) AS token_len
FROM public.users
WHERE id = 1;
