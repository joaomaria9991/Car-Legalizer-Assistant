import * as pdfjs from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.mjs?url";
import type { UploadPage } from "./types";

pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

const IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);

export async function splitFilesForUpload(files: File[]): Promise<UploadPage[]> {
  const pages: UploadPage[] = [];

  for (const file of files) {
    if (file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf")) {
      pages.push(...await splitPdf(file));
      continue;
    }

    if (IMAGE_TYPES.has(file.type) || /\.(png|jpe?g|webp)$/i.test(file.name)) {
      pages.push(await imageToJpegPage(file));
    }
  }

  return pages;
}

async function splitPdf(file: File): Promise<UploadPage[]> {
  const data = await file.arrayBuffer();
  const pdf = await pdfjs.getDocument({ data }).promise;
  const pages: UploadPage[] = [];
  const stem = file.name.replace(/\.[^.]+$/, "");

  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 2 });
    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");
    if (!context) {
      throw new Error("Canvas rendering is not available in this browser.");
    }

    canvas.width = viewport.width;
    canvas.height = viewport.height;
    await page.render({ canvas, canvasContext: context, viewport }).promise;

    const blob = await canvasToBlob(canvas, "image/jpeg", 0.86);
    pages.push({
      filename: `${stem}_page_${pageNumber}.jpg`,
      blob,
      sourceName: file.name,
      pageNumber,
    });
  }

  return pages;
}

async function imageToJpegPage(file: File): Promise<UploadPage> {
  const bitmap = await createImageBitmap(file);
  const canvas = document.createElement("canvas");
  canvas.width = bitmap.width;
  canvas.height = bitmap.height;
  const context = canvas.getContext("2d");
  if (!context) {
    throw new Error("Canvas rendering is not available in this browser.");
  }

  context.fillStyle = "#fff";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(bitmap, 0, 0);
  bitmap.close();

  const blob = await canvasToBlob(canvas, "image/jpeg", 0.88);
  return {
    filename: `${file.name.replace(/\.[^.]+$/, "")}_page_1.jpg`,
    blob,
    sourceName: file.name,
    pageNumber: 1,
  };
}

function canvasToBlob(canvas: HTMLCanvasElement, type: string, quality: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (blob) {
        resolve(blob);
      } else {
        reject(new Error("Could not convert canvas to image."));
      }
    }, type, quality);
  });
}
