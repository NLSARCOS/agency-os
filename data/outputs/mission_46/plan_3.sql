-- Chunked migration for existing data
DO $$
DECLARE
    batch_size INT := 1000;
    last_id UUID := '00000000-0000-0000-0000-000000000000';
BEGIN
    LOOP
        UPDATE proposals 
        SET tenant_id = '00000000-0000-0000-0000-000000000000'
        WHERE id > last_id 
        AND tenant_id IS NULL
        LIMIT batch_size;
        
        EXIT WHEN NOT FOUND;
        PERFORM pg_sleep(0.1); -- Rate limiting
    END LOOP;
END $$;