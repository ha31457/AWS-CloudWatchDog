.PHONY: install test build clean

# Install all dependencies (runtime + test)
install:
	pip install -r requirements.txt

# Run test suite
test:
	pytest tests/ -v

# Build Lambda deployment zip with vendored dependencies
build: clean
	pip install requests==2.31.0 -t lambda/vendor/ --no-deps
	cd lambda && zip -r ../function.zip . && cd ..

# Clean build artifacts
clean:
	rm -f function.zip
	rm -rf lambda/vendor/
