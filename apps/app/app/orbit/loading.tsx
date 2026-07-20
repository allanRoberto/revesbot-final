import styles from './page.module.css';

export default function Loading() {
  return (
    <main className={styles.page}>
      <div className={styles.skeletonGrid}>
        {[0, 1, 2].map((item) => <div className={styles.skeleton} key={item} />)}
      </div>
    </main>
  );
}
